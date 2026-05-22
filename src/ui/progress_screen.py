"""Tela de progresso do batch (Story 3.1).

Implementa a Tela 2 do fluxo do PA:
- Zone A: título "Processando batch" + indicador de etapa atual
- Zone B: barra de progresso + contador de lotes processados/com erro
- Zone C: checklist das etapas pós-batch (calibração → plágio → grupos)

Fluxo:

1. Lê ``st.session_state["batch_config"]`` (gravado pela Story 3.0). Se
   ausente/inválido, exibe erro e oferece "← Voltar ao upload".
2. Dispara :func:`src.batch.batch_processor.processar_batch` em
   ``threading.Thread(daemon=True)`` separada.
3. A cada 2 segundos, faz polling em ``batch_state`` via SELECT COUNT(*)
   (nunca via :func:`recuperar_fichas_batch` — evita deserializar todas
   as fichas a cada rerun, conforme nota de performance do AC-03).
4. Quando a thread termina, executa em sequência:
   :func:`calibrar_batch`, :func:`detectar_plagio_no_batch`,
   :func:`detectar_grupos_candidatos` — cada uma com ``st.spinner``.
5. Grava ``st.session_state["batch_results"]`` e redireciona para
   ``pages/3_validacao.py`` (Story 3.2).

Erros tratados:

* :class:`OrcamentoExcedidoError` na thread → ``st.error`` com
  estimativa vs limite; sem navegação para validação.
* Exceção genérica na thread → ``st.error`` técnico + opção de voltar.

Conformidade ADR-004: nenhuma PII é exibida nesta tela — apenas
contadores agregados (``X de Y alunos corrigidos``).
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from typing import Any

import streamlit as st

from src.batch import batch_state
from src.batch.batch_processor import processar_batch
from src.batch.calibrator import calibrar_batch
from src.batch.exceptions import OrcamentoExcedidoError
from src.batch.group_detector import AlunoRef, detectar_grupos_candidatos
from src.batch.plagiarism_detector import (
    TrabalhoParaComparacao,
    detectar_plagio_no_batch,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Intervalo entre reruns enquanto a thread do batch está viva (AC-03).
POLL_INTERVAL_SEG = 2

#: Página da Story 3.2 para onde redirecionamos ao final (AC-07).
PAGINA_VALIDACAO = "pages/3_validacao.py"

#: Página da Story 3.0 (link "Voltar ao upload" em caso de erro).
PAGINA_UPLOAD = "pages/1_upload.py"


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem Streamlit)
# ---------------------------------------------------------------------------


def batch_config_valido(config: dict[str, Any] | None) -> bool:
    """Valida estrutura mínima de ``st.session_state['batch_config']`` (AC-01).

    Estrutura esperada (gravada por upload_screen.render):
    ``{"alunos": list[dict], "enunciado": str, "metadata": dict}``.

    Retorna ``False`` se ``config`` é ``None``, não é dict, está sem alguma
    chave obrigatória, ou se ``alunos`` está vazio / ``enunciado`` está
    vazio.
    """
    if not isinstance(config, dict):
        return False
    if "alunos" not in config or "enunciado" not in config:
        return False
    alunos = config.get("alunos")
    enunciado = config.get("enunciado")
    if not isinstance(alunos, list) or not alunos:
        return False
    return isinstance(enunciado, str) and bool(enunciado.strip())


def calcular_progresso(lotes_concluidos: int, total_lotes: int) -> float:
    """Calcula razão ``lotes_concluidos / total_lotes`` em [0.0, 1.0] (AC-03).

    Guards:
    - ``total_lotes <= 0`` → ``0.0`` (evita divisão por zero).
    - ``lotes_concluidos > total_lotes`` → satura em ``1.0``.
    - Valores negativos → ``0.0``.
    """
    if total_lotes <= 0:
        return 0.0
    if lotes_concluidos <= 0:
        return 0.0
    razao = lotes_concluidos / total_lotes
    return min(razao, 1.0)


def formatar_contador_lotes(
    lotes_concluidos: int,
    total_lotes: int,
    alunos_corrigidos: int,
) -> str:
    """Formata texto do contador exibido sob a barra (AC-04).

    Ex: ``"Processando lote 3 de 12 — 36 alunos corrigidos"``.
    Quando ``lotes_concluidos == total_lotes``, usa o tempo presente
    ``"Lote X de Y"`` em vez de ``"Processando lote..."``.
    """
    if total_lotes <= 0:
        return "Aguardando início do processamento..."
    if lotes_concluidos >= total_lotes:
        return f"Lote {total_lotes} de {total_lotes} — {alunos_corrigidos} alunos corrigidos"
    proximo = min(lotes_concluidos + 1, total_lotes)
    return f"Processando lote {proximo} de {total_lotes} — {alunos_corrigidos} alunos corrigidos"


def construir_batch_results(
    resultado: dict[str, Any],
    fichas_calibradas: list[Any],
    alertas_plagio: list[Any],
    grupos_candidatos: list[Any],
) -> dict[str, Any]:
    """Monta o dict ``st.session_state['batch_results']`` (AC-07).

    Estrutura fixa, consumida pela Story 3.2:
    ``{"fichas_calibradas", "alertas_plagio", "grupos_candidatos",
       "custo_estimado_brl", "lotes_com_erro"}``.
    """
    return {
        "fichas_calibradas": fichas_calibradas,
        "alertas_plagio": alertas_plagio,
        "grupos_candidatos": grupos_candidatos,
        "custo_estimado_brl": float(resultado.get("custo_estimado_brl", 0.0)),
        "lotes_com_erro": int(resultado.get("lotes_com_erro", 0)),
    }


def contar_lotes_concluidos(batch_id: int) -> int:
    """Conta lotes com status='processado' via SELECT COUNT(*) (AC-03 — nota de performance).

    Usa sqlite3 diretamente em vez de ``batch_state.recuperar_fichas_batch()``
    para evitar deserializar centenas de fichas a cada rerun de 2s.
    Falha silenciosa (retorna ``0``) — não bloqueia a UI se o banco ainda
    não existe.
    """
    try:
        with sqlite3.connect(batch_state.DB_PATH) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM lotes WHERE batch_id=? AND status='processado'",
                (batch_id,),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def contar_lotes_com_erro(batch_id: int) -> int:
    """Conta lotes com status='falha' via SELECT COUNT(*) (AC-05).

    Falha silenciosa (retorna ``0``) — segue padrão de
    :func:`contar_lotes_concluidos`.
    """
    try:
        with sqlite3.connect(batch_state.DB_PATH) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM lotes WHERE batch_id=? AND status='falha'",
                (batch_id,),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def listar_motivos_falha(batch_id: int) -> list[tuple[int, str]]:
    """Lista ``(lote_num, motivo)`` de todos os lotes com status='falha' (AC-05).

    Falha silenciosa (retorna ``[]``).
    """
    try:
        with sqlite3.connect(batch_state.DB_PATH) as conn:
            rows = conn.execute(
                "SELECT lote_num, COALESCE(erro_msg, 'erro_desconhecido') "
                "FROM lotes WHERE batch_id=? AND status='falha' ORDER BY lote_num",
                (batch_id,),
            ).fetchall()
            return [(int(lote_num), str(motivo)) for lote_num, motivo in rows]
    except sqlite3.Error:
        return []


def contar_alunos_corrigidos(batch_id: int) -> int:
    """Soma ``processados`` de todos os lotes do batch.

    Falha silenciosa (retorna ``0``).
    """
    try:
        with sqlite3.connect(batch_state.DB_PATH) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(processados), 0) FROM lotes WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


# ---------------------------------------------------------------------------
# Worker thread (escreve em st.session_state via funções módulo)
# ---------------------------------------------------------------------------


def _run_batch(
    config: dict[str, Any],
    estado: dict[str, Any],
) -> None:
    """Executa ``processar_batch`` e grava resultado/erro em ``estado``.

    ``estado`` é um dict compartilhado com o thread principal (referência
    armazenada em ``st.session_state``). Evita acesso direto a
    ``st.session_state`` aqui — não é thread-safe em todos os contextos
    do Streamlit.
    """
    try:
        resultado = processar_batch(
            alunos=config["alunos"],
            enunciado=config["enunciado"],
            metadata=config.get("metadata", {}),
        )
        estado["resultado"] = resultado
    except OrcamentoExcedidoError as e:
        estado["erro_orcamento"] = e
    except Exception as e:  # noqa: BLE001 — registra qualquer falha para a UI
        estado["erro_generico"] = e


# ---------------------------------------------------------------------------
# Helpers de etapa pós-batch (chamados pelo render — não puros)
# ---------------------------------------------------------------------------


def _construir_trabalhos_para_comparacao(
    alunos: list[dict[str, Any]],
) -> list[TrabalhoParaComparacao]:
    """Converte lista de alunos do batch_config em entrada do detector de plágio."""
    return [
        TrabalhoParaComparacao(
            aluno_id=str(a.get("ra", "")).strip(),
            texto=str(a.get("resposta", "")),
        )
        for a in alunos
    ]


def _construir_alunos_ref(
    alunos: list[dict[str, Any]],
    nomes_por_ra: dict[str, str],
) -> list[AlunoRef]:
    """Converte (alunos do batch + nomes_por_ra do upload) em ``list[AlunoRef]``.

    O ``group_detector`` precisa de ``nome`` para fuzzy matching — usamos
    apenas o mapa local ``nomes_por_ra`` (já carregado na Story 3.0).
    """
    refs: list[AlunoRef] = []
    for a in alunos:
        ra = str(a.get("ra", "")).strip()
        if not ra:
            continue
        nome = nomes_por_ra.get(ra, "").strip()
        if not nome:
            continue
        refs.append(AlunoRef(ra=ra, nome=nome))
    return refs


# ---------------------------------------------------------------------------
# Componente Streamlit principal
# ---------------------------------------------------------------------------


def _resetar_estado_batch() -> None:
    """Limpa as chaves de controle de batch do session_state.

    Chamado após erro ou quando o usuário escolhe voltar ao upload.
    """
    for chave in (
        "_batch_thread",
        "_batch_estado",
        "_batch_id_corrente",
        "_etapa_pos_batch",
    ):
        st.session_state.pop(chave, None)


def _voltar_ao_upload() -> None:
    """Reseta estado e navega para a tela 1."""
    _resetar_estado_batch()
    # Em testes sem contexto multi-page, switch_page levanta — suprimimos.
    with contextlib.suppress(Exception):
        st.switch_page(PAGINA_UPLOAD)


def render() -> None:
    """Renderiza a tela de progresso.

    Função principal — chamada por ``pages/2_progresso.py``.
    """
    st.title("Corretor Acadêmico — Processando batch")
    st.markdown("---")

    # -----------------------------------------------------------------------
    # AC-01 — Valida batch_config ANTES de qualquer outra ação
    # -----------------------------------------------------------------------
    config = st.session_state.get("batch_config")
    if not batch_config_valido(config):
        st.error(
            "Configuração do batch ausente ou inválida. "
            "Você precisa concluir a Tela 1 (upload + enunciado) antes de iniciar o processamento."
        )
        if st.button("← Voltar ao upload", type="primary"):
            _voltar_ao_upload()
        return

    # Para o mypy e legibilidade — config é dict válido a partir daqui.
    assert isinstance(config, dict)
    alunos: list[dict[str, Any]] = list(config["alunos"])
    total_alunos = len(alunos)

    # batch_id é gerado dentro de processar_batch via AUTOINCREMENT. O
    # primeiro batch após limpar_banco() sempre tem id=1 (sqlite reseta
    # sequência ao DELETE) — utilizamos esse pressuposto para o polling.

    # -----------------------------------------------------------------------
    # AC-02 — inicia thread se ainda não rodou
    # -----------------------------------------------------------------------
    if "_batch_thread" not in st.session_state:
        estado_inicial: dict[str, Any] = {
            "resultado": None,
            "erro_orcamento": None,
            "erro_generico": None,
        }
        nova_thread = threading.Thread(
            target=_run_batch,
            args=(config, estado_inicial),
            daemon=True,
            name="batch-processor",
        )
        st.session_state["_batch_estado"] = estado_inicial
        st.session_state["_batch_thread"] = nova_thread
        st.session_state["_batch_id_corrente"] = 1  # primeiro batch após reset
        nova_thread.start()

    thread: threading.Thread = st.session_state["_batch_thread"]
    estado: dict[str, Any] = st.session_state["_batch_estado"]
    batch_id = int(st.session_state.get("_batch_id_corrente", 1))

    # -----------------------------------------------------------------------
    # AC-08 — checa erro de orçamento ANTES de tentar exibir progresso
    # -----------------------------------------------------------------------
    if estado.get("erro_orcamento") is not None:
        err: OrcamentoExcedidoError = estado["erro_orcamento"]
        st.error(
            "Orçamento excedido — batch não foi iniciado.\n\n"
            f"**Estimativa:** R$ {err.estimativa_brl:.2f}\n\n"
            f"**Limite (MAX_COST_BRL):** R$ {err.limite_brl:.2f}\n\n"
            f"**Excesso:** R$ {err.excesso_brl:.2f}"
        )
        if st.button("← Voltar ao upload", type="primary"):
            _voltar_ao_upload()
        return

    # -----------------------------------------------------------------------
    # Erro genérico na thread → exibe e oferece retorno
    # -----------------------------------------------------------------------
    if estado.get("erro_generico") is not None:
        err_gen: Exception = estado["erro_generico"]
        st.error(f"Falha inesperada no processamento: {err_gen}")
        if st.button("← Voltar ao upload", type="primary"):
            _voltar_ao_upload()
        return

    # -----------------------------------------------------------------------
    # AC-03 + AC-04 — barra de progresso + contador
    # -----------------------------------------------------------------------
    # Estimativa de total_lotes: BATCH_SIZE vem de packages.wrapper.clone_client.
    # Para evitar acoplamento, calculamos via ceil(total_alunos / BATCH_SIZE).
    from packages.wrapper.clone_client import BATCH_SIZE  # noqa: PLC0415 — lazy

    total_lotes = max(1, -(-total_alunos // BATCH_SIZE))  # ceil

    lotes_concluidos = contar_lotes_concluidos(batch_id)
    lotes_com_erro_atual = contar_lotes_com_erro(batch_id)
    alunos_corrigidos = contar_alunos_corrigidos(batch_id)

    razao = calcular_progresso(lotes_concluidos + lotes_com_erro_atual, total_lotes)
    st.progress(razao)
    st.markdown(f"**{formatar_contador_lotes(lotes_concluidos, total_lotes, alunos_corrigidos)}**")

    # AC-05 — falhas inline (não interrompem a barra)
    motivos = listar_motivos_falha(batch_id)
    if motivos:
        with st.expander(f"⚠️ {len(motivos)} lote(s) com falha — clique para detalhes"):
            for lote_num, motivo in motivos:
                st.warning(f"Lote {lote_num}: {motivo}")

    # -----------------------------------------------------------------------
    # Thread ainda viva: polling via rerun a cada 2s
    # -----------------------------------------------------------------------
    if thread.is_alive():
        time.sleep(POLL_INTERVAL_SEG)
        st.rerun()
        return  # nunca executa, mas explicito

    # -----------------------------------------------------------------------
    # Thread terminou e sem erros — etapas pós-batch (AC-06)
    # -----------------------------------------------------------------------
    resultado = estado.get("resultado")
    if resultado is None:
        # Edge case: thread morreu sem gravar nem resultado nem erro
        st.error("Processamento finalizou em estado inconsistente. Tente novamente.")
        if st.button("← Voltar ao upload", type="primary"):
            _voltar_ao_upload()
        return

    # Fichas do batch (lista de dicts deserializados — batch_state.recuperar_fichas_batch
    # retorna dicts, não objetos FichaCorrecao; a conversão é responsabilidade
    # do calibrador, que aceita ambos via duck typing).
    fichas_brutas = resultado.get("resultados", [])

    st.markdown("---")
    st.subheader("Etapas pós-batch")

    # Etapa 1 — Calibração
    with st.spinner("Calibrando notas com Sonnet..."):
        try:
            fichas_calibradas = calibrar_batch(
                fichas=fichas_brutas,
                metadata=config.get("metadata", {}),
            )
        except Exception as e:  # noqa: BLE001 — calibração não deve derrubar a UI
            st.error(f"Falha na calibração: {e}")
            return
    st.success(f"✅ Calibração concluída — {len(fichas_calibradas)} fichas")

    # Etapa 2 — Detecção de plágio (AC-06 fixa essa ordem)
    nomes_por_ra: dict[str, str] = st.session_state.get("nomes_por_ra", {})
    trabalhos = _construir_trabalhos_para_comparacao(alunos)

    with st.spinner("Detectando plágio entre trabalhos..."):
        try:
            alertas_plagio = detectar_plagio_no_batch(trabalhos=trabalhos)
        except Exception as e:  # noqa: BLE001
            st.error(f"Falha na detecção de plágio: {e}")
            return
    st.success(f"✅ Detecção de plágio concluída — {len(alertas_plagio)} alerta(s)")

    # Etapa 3 — Detecção de grupos candidatos
    # Nota: AC-06 fixa a ordem plágio→grupos; portanto NÃO repassamos
    # ``grupos_conhecidos`` ao detector de plágio nesta tela. A Story 3.2
    # pode aplicar a supressão visual usando ambos os resultados.
    with st.spinner("Detectando grupos candidatos..."):
        try:
            alunos_ref = _construir_alunos_ref(alunos, nomes_por_ra)
            grupos_candidatos = detectar_grupos_candidatos(
                trabalhos=trabalhos,
                alunos=alunos_ref,
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"Falha na detecção de grupos: {e}")
            return
    st.success(f"✅ Detecção de grupos concluída — {len(grupos_candidatos)} grupo(s) candidato(s)")

    # -----------------------------------------------------------------------
    # AC-07 — grava batch_results e navega para validação
    # -----------------------------------------------------------------------
    st.session_state["batch_results"] = construir_batch_results(
        resultado=resultado,
        fichas_calibradas=fichas_calibradas,
        alertas_plagio=alertas_plagio,
        grupos_candidatos=grupos_candidatos,
    )

    # Limpa estado de controle para permitir novo batch numa próxima sessão
    _resetar_estado_batch()

    st.success("Processamento completo! Redirecionando para a tela de validação...")
    # Em testes sem contexto multi-page, switch_page levanta — caímos no info.
    try:
        st.switch_page(PAGINA_VALIDACAO)
    except Exception:  # noqa: BLE001 — multi-page indisponível no contexto atual
        st.info(
            "Use o menu lateral para abrir 'validação' "
            "(switch_page indisponível no contexto atual)."
        )
