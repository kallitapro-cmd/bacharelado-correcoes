"""Orquestrador de lotes do Corretor Acadêmico (Story 2.2).

Recebe a lista completa de alunos da Aba 1, particiona em lotes de
``BATCH_SIZE`` (ADR-002, veto V8), distribui o trabalho via
``ThreadPoolExecutor`` e persiste o estado intermediário via funções públicas
do módulo ``src.batch.batch_state`` (Story 2.6) — NUNCA acessa sqlite3
diretamente.

Aplica os guardrails da política de orçamento (ADR-005):

* Estimativa de custo calculada ANTES de qualquer chamada à API.
* Bloqueio com :class:`OrcamentoExcedidoError` se a estimativa exceder
  ``MAX_COST_BRL`` (lido de ``st.secrets`` com fallback ``15.0``).

Resolve MNT-003 (Sprint 1) introduzindo :class:`AcaoBatch` como contrato
formal para todos os payloads de ``log_action()``.
"""

from __future__ import annotations

import contextlib
import threading
import time
import types
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any

import streamlit as st
from packages.wrapper.clone_client import BATCH_SIZE, corrigir_aluno
from packages.wrapper.exceptions import (
    ClonTruncatedResponseError,
    ClonValidationError,
)

from src.batch import batch_state
from src.batch.exceptions import OrcamentoExcedidoError
from src.utils.audit_log import log_action

# ---------------------------------------------------------------------------
# AC-13 — Lock de módulo serializa escritas em batch_state (sqlite3 + threads)
# ---------------------------------------------------------------------------

_db_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# AC-10 — Enum AcaoBatch resolve MNT-003 (Sprint 1)
# ---------------------------------------------------------------------------


class AcaoBatch(str, Enum):  # noqa: UP042 — story exige (str, Enum), não StrEnum
    """Ações estruturadas para ``log_action()`` (resolve MNT-003).

    Mantemos ``(str, Enum)`` em vez de ``StrEnum`` por requisito explícito da
    Story 2.2 (AC-10) e para compatibilidade com Python 3.10 — ``StrEnum`` só
    existe a partir do 3.11. O comportamento ``isinstance(membro, str)`` é
    idêntico ao de ``StrEnum``.
    """

    BATCH_INICIADO = "batch_iniciado"
    LOTE_PROCESSADO = "lote_processado"
    LOTE_ERRO = "lote_erro"
    BATCH_CONCLUIDO = "batch_concluido"


# ---------------------------------------------------------------------------
# AC-05 / AC-06 — Status de revisão manual
# ---------------------------------------------------------------------------

STATUS_TRUNCADA = "REVISÃO MANUAL — TRUNCADA"
STATUS_VALIDACAO = "REVISÃO MANUAL — VALIDAÇÃO"
STATUS_RATE_LIMIT = "REVISÃO MANUAL — RATE LIMIT"


# ---------------------------------------------------------------------------
# Fórmula de estimativa (ADR-005) — referência maio/2026
# ---------------------------------------------------------------------------

PRECO_HAIKU_IN = 0.80  # USD por 1M tokens de entrada
PRECO_HAIKU_OUT = 4.00  # USD por 1M tokens de saída
PRECO_SONNET_IN = 3.00  # USD por 1M tokens de entrada
PRECO_SONNET_OUT = 15.00  # USD por 1M tokens de saída
TAXA_CAMBIO = 5.50  # USD → BRL
TOKENS_IN_HAIKU = 4_000
TOKENS_OUT_HAIKU = 4_096
TOKENS_IN_SONNET = 3_000
TOKENS_OUT_SONNET = 4_096


def estimar_custo_brl(n_lotes: int, n_regeneracoes: int = 3) -> float:
    """Calcula o custo estimado em BRL conforme fórmula do ADR-005.

    Args:
        n_lotes: número de lotes Haiku (correção inicial).
        n_regeneracoes: número de regenerações Haiku esperadas (default 3).

    Returns:
        Custo total estimado em BRL, somando Haiku + Sonnet (calibrador) + regen.
    """
    custo_haiku = (
        n_lotes
        * (TOKENS_IN_HAIKU * PRECO_HAIKU_IN + TOKENS_OUT_HAIKU * PRECO_HAIKU_OUT)
        / 1_000_000
    )
    custo_sonnet = (
        1 * (TOKENS_IN_SONNET * PRECO_SONNET_IN + TOKENS_OUT_SONNET * PRECO_SONNET_OUT) / 1_000_000
    )
    custo_regen = (
        n_regeneracoes
        * (TOKENS_IN_HAIKU * PRECO_HAIKU_IN + TOKENS_OUT_HAIKU * PRECO_HAIKU_OUT)
        / 1_000_000
    )
    return (custo_haiku + custo_sonnet + custo_regen) * TAXA_CAMBIO


def _get_max_cost_brl() -> float:
    """Lê ``MAX_COST_BRL`` de ``st.secrets`` com fallback ``15.0`` (AC-09).

    ``st.secrets`` pode levantar exceção fora do contexto Streamlit
    (ex.: testes unitários) — try/except trata isso silenciosamente.
    """
    try:
        return float(st.secrets.get("MAX_COST_BRL", "15.0"))
    except (ValueError, TypeError, AttributeError, FileNotFoundError, Exception):  # noqa: BLE001
        return 15.0


# ---------------------------------------------------------------------------
# Auxiliares internos
# ---------------------------------------------------------------------------


def _safe_log_action(acao: AcaoBatch, payload_resumido: str = "") -> None:
    """Wrapper sobre ``log_action()`` tolerante a ausência de contexto Streamlit.

    Em testes unitários ``st.session_state`` pode não existir — preferimos
    silenciar falhas de log a abortar o processamento do batch.
    """
    # Falha de log nunca aborta o batch — apenas perde a entrada.
    with contextlib.suppress(Exception):
        log_action(acao=acao.value, payload_resumido=payload_resumido)


def _particionar(alunos: list[dict[str, Any]], tamanho: int) -> list[list[dict[str, Any]]]:
    """Divide ``alunos`` em lotes contínuos de tamanho ``tamanho``."""
    return [alunos[i : i + tamanho] for i in range(0, len(alunos), tamanho)]


def _to_simple_ns(resultado_bruto: Any) -> list[types.SimpleNamespace]:
    """Converte retorno de ``corrigir_aluno()`` em lista de SimpleNamespace (AC-16).

    ``corrigir_aluno()`` retorna ``RespostaBatch`` (Pydantic) com atributo
    ``.fichas`` (lista de ``FichaCorrecao``). Os testes mockam isso e podem
    retornar tanto objetos Pydantic-like quanto listas de dicts — tratamos
    ambos os formatos para máxima robustez.
    """
    # Caso 1: objeto com .fichas (RespostaBatch real ou mock equivalente)
    fichas = getattr(resultado_bruto, "fichas", None)
    if fichas is not None:
        return [
            f
            if hasattr(f, "ra")
            else types.SimpleNamespace(**(f if isinstance(f, dict) else vars(f)))
            for f in fichas
        ]

    # Caso 2: lista direta de dicts/objetos
    if isinstance(resultado_bruto, list):
        return [
            (
                types.SimpleNamespace(**item)
                if isinstance(item, dict)
                else (item if hasattr(item, "ra") else types.SimpleNamespace(**vars(item)))
            )
            for item in resultado_bruto
        ]

    # Caso 3: formato inesperado — devolve lista vazia (não derruba o batch)
    return []


def _construir_fichas_revisao(
    alunos_lote: list[dict[str, Any]], status: str
) -> list[types.SimpleNamespace]:
    """Cria fichas placeholder com status de revisão manual para um lote falho.

    Usado quando ``ClonValidationError`` ou ``ClonTruncatedResponseError``
    impede a obtenção das fichas reais — preservamos uma ficha por aluno do
    lote para que a UI consiga sinalizar o que precisa de revisão.
    """
    fichas: list[types.SimpleNamespace] = []
    for aluno in alunos_lote:
        ra = str(aluno.get("ra", "")) if isinstance(aluno, dict) else str(getattr(aluno, "ra", ""))
        fichas.append(
            types.SimpleNamespace(
                ra=ra,
                status=status,
                nota_a1=None,
                feedback="",
                confianca="baixa",
                flags=["revisao_manual"],
            )
        )
    return fichas


def _processar_um_lote(
    client: Any,
    alunos_lote: list[dict[str, Any]],
    enunciado: str,
    metadata: dict[str, Any],
) -> list[types.SimpleNamespace]:
    """Chama ``corrigir_aluno()`` com retry para 429 (AC-15).

    Retorna lista de fichas com ``.ra``. Em caso de rate limit esgotado,
    re-levanta a última exceção para o caller marcar o lote como falha.

    ``ClonValidationError`` e ``ClonTruncatedResponseError`` são propagados
    IMEDIATAMENTE (sem retry) — falhas determinísticas, retry não ajuda.
    """
    payload = {
        "alunos": alunos_lote,
        "enunciado": enunciado,
        "metadata": metadata,
    }

    last_exc: Exception | None = None
    for tentativa in range(3):
        try:
            resultado = corrigir_aluno(client, payload)
            return _to_simple_ns(resultado)
        except (ClonValidationError, ClonTruncatedResponseError):
            # Falhas determinísticas — propaga sem retry
            raise
        except Exception as e:  # noqa: BLE001
            last_exc = e
            msg = str(e).lower()
            is_rate_limit = "429" in msg or "rate limit" in msg or "rate_limit" in msg
            if is_rate_limit and tentativa < 2:
                time.sleep(10 * 2**tentativa)  # 10s, 20s
                continue
            # Outras exceções inesperadas: propaga
            raise

    # 3 tentativas falharam por rate limit
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------


def processar_batch(
    alunos: list[dict[str, Any]],
    enunciado: str,
    metadata: dict[str, Any],
    max_workers: int = 3,
    n_regeneracoes: int = 3,
    client: Any = None,
) -> dict[str, Any]:
    """Orquestra a correção em lotes.

    Args:
        alunos: lista de dicts (cada um com pelo menos a chave ``ra``).
        enunciado: enunciado do trabalho avaliado.
        metadata: metadados do lote (turma, professor, etc.).
        max_workers: tamanho do pool ``ThreadPoolExecutor`` (default 3).
        n_regeneracoes: nº de regenerações Haiku para fins de estimativa.
        client: cliente Anthropic já instanciado (injetado para testes).

    Returns:
        ``{"resultados": [...], "custo_estimado_brl": float,
           "lotes_processados": int, "lotes_com_erro": int}``

    Raises:
        OrcamentoExcedidoError: se ``custo_estimado_brl > MAX_COST_BRL``
            (ADR-005) — levantada ANTES de qualquer chamada à API.
    """
    total_alunos = len(alunos)
    lotes = _particionar(alunos, BATCH_SIZE)
    n_lotes = len(lotes)

    # AC-07 / AC-08 — estimativa de custo ANTES de qualquer chamada à API
    custo_estimado = estimar_custo_brl(n_lotes=n_lotes, n_regeneracoes=n_regeneracoes)
    limite = _get_max_cost_brl()
    if custo_estimado > limite:
        raise OrcamentoExcedidoError(estimativa_brl=custo_estimado, limite_brl=limite)

    # AC-03 — toda persistência via batch_state (NUNCA sqlite3 direto)
    # ``inicializar_banco()`` antes do limpar garante que as tabelas existam
    # mesmo em /tmp/ recém-criado (filesystem efêmero do Streamlit Cloud).
    # A sequência canônica (limpar → inicializar → criar_batch) é mantida
    # logo em seguida — a primeira chamada de init é idempotente.
    batch_state.inicializar_banco()
    batch_state.limpar_banco()
    batch_state.inicializar_banco()
    sessao_id = uuid.uuid4().hex
    batch_id = batch_state.criar_batch(sessao_id=sessao_id, total_alunos=total_alunos)

    _safe_log_action(
        AcaoBatch.BATCH_INICIADO,
        payload_resumido=f"total_alunos={total_alunos}, n_lotes={n_lotes}",
    )

    lotes_com_erro = 0
    lotes_processados = 0

    # AC-02 — ThreadPoolExecutor com max_workers configurável
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_lote: dict[Any, tuple[int, list[dict[str, Any]]]] = {}
        for idx, lote in enumerate(lotes, start=1):
            future = executor.submit(_processar_um_lote, client, lote, enunciado, metadata)
            future_to_lote[future] = (idx, lote)

        for future in as_completed(future_to_lote):
            lote_num, alunos_lote = future_to_lote[future]
            try:
                fichas = future.result()
                # AC-13 — escrita serializada
                with _db_write_lock:
                    batch_state.salvar_lote(batch_id, lote_num, fichas)
                lotes_processados += 1
                _safe_log_action(
                    AcaoBatch.LOTE_PROCESSADO,
                    payload_resumido=f"lote {lote_num}/{n_lotes}, {len(alunos_lote)} alunos",
                )
            except ClonTruncatedResponseError:
                # AC-04 / AC-05
                lotes_com_erro += 1
                fichas_rev = _construir_fichas_revisao(alunos_lote, STATUS_TRUNCADA)
                with _db_write_lock:
                    batch_state.salvar_lote(batch_id, lote_num, fichas_rev)
                    batch_state.marcar_lote_falha(batch_id, lote_num, "resposta_truncada")
                _safe_log_action(
                    AcaoBatch.LOTE_ERRO,
                    payload_resumido=(f"lote {lote_num}/{n_lotes}, motivo=resposta_truncada"),
                )
            except ClonValidationError:
                # AC-04 / AC-06
                lotes_com_erro += 1
                fichas_rev = _construir_fichas_revisao(alunos_lote, STATUS_VALIDACAO)
                with _db_write_lock:
                    batch_state.salvar_lote(batch_id, lote_num, fichas_rev)
                    batch_state.marcar_lote_falha(batch_id, lote_num, "falha_validacao")
                _safe_log_action(
                    AcaoBatch.LOTE_ERRO,
                    payload_resumido=(f"lote {lote_num}/{n_lotes}, motivo=falha_validacao"),
                )
            except Exception as e:  # noqa: BLE001
                # AC-15 — rate limit esgotado ou erro inesperado: falha isolada do lote
                lotes_com_erro += 1
                msg = str(e).lower()
                motivo = (
                    "rate_limit_esgotado"
                    if ("429" in msg or "rate limit" in msg or "rate_limit" in msg)
                    else "erro_inesperado"
                )
                status_rev = (
                    STATUS_RATE_LIMIT if motivo == "rate_limit_esgotado" else STATUS_VALIDACAO
                )
                fichas_rev = _construir_fichas_revisao(alunos_lote, status_rev)
                with _db_write_lock:
                    batch_state.salvar_lote(batch_id, lote_num, fichas_rev)
                    batch_state.marcar_lote_falha(batch_id, lote_num, motivo)
                _safe_log_action(
                    AcaoBatch.LOTE_ERRO,
                    payload_resumido=f"lote {lote_num}/{n_lotes}, motivo={motivo}",
                )

    _safe_log_action(
        AcaoBatch.BATCH_CONCLUIDO,
        payload_resumido=(
            f"processados={lotes_processados}, com_erro={lotes_com_erro}, total_lotes={n_lotes}"
        ),
    )

    resultados = batch_state.recuperar_fichas_batch(batch_id)

    return {
        "resultados": resultados,
        "custo_estimado_brl": custo_estimado,
        "lotes_processados": lotes_processados,
        "lotes_com_erro": lotes_com_erro,
    }
