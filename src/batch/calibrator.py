"""Calibrador estatístico de notas do batch (Story 2.3).

Recebe a lista completa de :class:`FichaCorrecao` produzida pelo
``batch_processor`` e calibra o ranking de notas em **uma única chamada**
à API Anthropic com ``claude-sonnet-4-6`` (ADR-003).

Aplica duas regras inegociáveis das heurísticas do squad
``bacharelado-correcoes``:

* **H-CAL-01 — top 10%:** os melhores ``ceil(0.10 × N_alunos)`` alunos
  do batch podem receber nota até ``10.0``. Em caso de empate no limiar,
  todos os empatados entram no top.
* **H-CAL-02 — cap 9:** todos os demais alunos têm a nota limitada a
  ``9.0`` — a faixa ``9.0–10.0`` é reservada para quem se destacou no
  ranking comparativo.

A pré-classificação do top 10% é feita em Python puro **antes** da
chamada à API. O Sonnet recebe apenas um ranking estruturado (RA + nota,
sem nomes — ADR-004) e devolve os ajustes finais de forma determinística
(``temperature=0``). O cap 9 é re-aplicado em Python no retorno para
garantir a regra mesmo se a IA divergir.

ADRs relevantes:

* **ADR-003** — modelo Sonnet, ``temperature=0``, ``max_tokens=4096``
* **ADR-002** — V6 (``timeout=90``) e V9 (``cache_control: ephemeral``)
* **ADR-004** — payload e logs sem PII (sem nomes, apenas RA + nota)
* **ADR-005** — custo Sonnet já contabilizado no ``batch_processor``;
  ``OrcamentoExcedidoError`` NÃO é levantada aqui.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.utils.audit_log import log_action

if TYPE_CHECKING:
    from packages.wrapper.schemas import FichaCorrecao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes (ADR-003 — fonte canônica de parâmetros de calibração)
# ---------------------------------------------------------------------------

#: Modelo usado na calibração (Sonnet — raciocínio comparativo entre alunos).
MODELO_CALIBRACAO = "claude-sonnet-4-6"

#: Temperature = 0 → ranking determinístico (auditabilidade ADR-003).
TEMPERATURE_CALIBRACAO = 0

#: Teto de tokens de saída — ADR-003 unificou em 4096.
MAX_TOKENS_CALIBRACAO = 4096

#: Timeout explícito do SDK Anthropic (V6 do ADR-002 — default do SDK é 600s).
API_TIMEOUT = 90

#: Cap aplicado a alunos fora do top 10% (H-CAL-02).
CAP_NOTA_FORA_DO_TOP = 9.0

#: Percentual do batch elegível à nota máxima (H-CAL-01).
PERCENTUAL_TOP = 0.10


# ---------------------------------------------------------------------------
# System prompt (compacto e cacheável — V9 ADR-002)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_CALIBRACAO = """Você é um calibrador de notas acadêmicas.

Recebe um ranking pré-classificado de alunos (apenas RA + nota bruta) e
retorna o mesmo ranking com notas ajustadas conforme as regras abaixo.

REGRAS (inegociáveis):
1. Top 10% (ceil de 10% do total) podem ter nota entre 9.0 e 10.0.
2. Todos os demais ficam com nota limitada a 9.0 (cap 9).
3. Empates no limiar do top entram no top — incluir todos os empatados.
4. NÃO inventar alunos. NÃO remover alunos. NÃO alterar RAs.

FORMATO DE RESPOSTA (JSON estrito, sem markdown, sem code fences):
{
  "ranking": [
    {"ra": "<11 dígitos>", "nota_ajustada": <float 0.0-10.0>},
    ...
  ]
}

A lista deve conter EXATAMENTE os mesmos RAs recebidos, na mesma ordem.
"""


# ---------------------------------------------------------------------------
# Helpers de pré-processamento (Python puro — independente da API)
# ---------------------------------------------------------------------------


def _calcular_top_n(total: int) -> int:
    """Calcula ``top_n = ceil(0.10 × total)`` — mínimo 1 quando há alunos."""
    return math.ceil(PERCENTUAL_TOP * total)


def _identificar_top_ras(fichas: list[FichaCorrecao], top_n: int) -> set[str]:
    """Retorna o conjunto de RAs que pertencem ao top 10% (com empates).

    Estratégia: ordena por ``nota_a1`` decrescente, identifica a
    ``nota_limiar`` na posição ``top_n - 1`` e inclui todos os RAs com
    ``nota_a1 >= nota_limiar``. Fichas com ``nota_a1 is None`` são
    tratadas como ``-1.0`` (não podem competir pelo top).
    """
    if not fichas or top_n <= 0:
        return set()

    notas_ordenadas = sorted(
        ((f.nota_a1 if f.nota_a1 is not None else -1.0) for f in fichas),
        reverse=True,
    )
    # top_n é ao menos 1 quando há fichas; clamp por segurança
    indice_limiar = min(top_n - 1, len(notas_ordenadas) - 1)
    nota_limiar = notas_ordenadas[indice_limiar]

    return {f.ra for f in fichas if (f.nota_a1 if f.nota_a1 is not None else -1.0) >= nota_limiar}


def _montar_payload_sonnet(fichas: list[FichaCorrecao], top_ras: set[str]) -> str:
    """Monta o user message: ranking compacto sem PII (apenas RA + nota).

    Inclui flag ``no_top`` para que o Sonnet saiba quais alunos estão
    elegíveis à nota > 9.0. Conforme ADR-004, NÃO inclui nomes, conteúdo
    dos trabalhos ou qualquer outro dado pessoal além do RA.
    """
    ranking = [
        {
            "ra": f.ra,
            "nota_bruta": f.nota_a1 if f.nota_a1 is not None else 0.0,
            "no_top": f.ra in top_ras,
        }
        for f in sorted(
            fichas,
            key=lambda x: x.nota_a1 if x.nota_a1 is not None else -1.0,
            reverse=True,
        )
    ]
    payload = {
        "total_alunos": len(fichas),
        "top_n": len(top_ras),
        "ranking": ranking,
        "instrucao": (
            "Retorne apenas o JSON conforme schema do system prompt. "
            "Aplique cap 9 aos alunos com no_top=false. Mantenha (ou ajuste "
            "levemente, sem ultrapassar 10.0) os alunos com no_top=true."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helpers de pós-processamento
# ---------------------------------------------------------------------------


def _parse_resposta_sonnet(raw: str) -> dict[str, float]:
    """Converte a resposta do Sonnet em ``{ra: nota_ajustada}``.

    Tolerante a respostas vazias/malformadas: em caso de falha de parsing,
    retorna dict vazio — o merge final aplicará apenas o cap 9 sobre as
    notas brutas, preservando a robustez do batch.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Resposta do Sonnet (calibração) não é JSON válido — "
            "aplicando apenas cap 9 sobre notas brutas."
        )
        return {}

    ranking = data.get("ranking") if isinstance(data, dict) else None
    if not isinstance(ranking, list):
        return {}

    ajustes: dict[str, float] = {}
    for item in ranking:
        if not isinstance(item, dict):
            continue
        ra = item.get("ra")
        nota = item.get("nota_ajustada")
        if not isinstance(ra, str):
            continue
        try:
            ajustes[ra] = float(nota)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return ajustes


def _aplicar_calibracao(
    ficha: FichaCorrecao,
    ajustes: dict[str, float],
    top_ras: set[str],
) -> FichaCorrecao:
    """Mescla nota ajustada e aplica cap 9 quando fora do top.

    Regra de merge:
    1. Se há ajuste retornado pelo Sonnet, usa-o como nota inicial.
    2. Caso contrário, mantém a nota bruta da ficha.
    3. Se o aluno NÃO está no top, aplica cap 9: ``min(nota, 9.0)``.
    4. Clamp final em ``[0.0, 10.0]`` para respeitar o schema.

    Falhas de validação do schema (raríssimas — Sonnet não devolve nota
    fora de [0,10] com ``temperature=0``) caem para a nota bruta com cap.
    """
    nota_bruta = ficha.nota_a1
    nota_ajustada = ajustes.get(ficha.ra, nota_bruta)

    # Preserva None: ficha sem nota original continua sem nota.
    if nota_ajustada is None:
        return ficha

    nota_final = float(nota_ajustada)
    if ficha.ra not in top_ras:
        nota_final = min(nota_final, CAP_NOTA_FORA_DO_TOP)
    # Clamp dentro de [0.0, 10.0] — respeita o constraint do schema.
    nota_final = max(0.0, min(10.0, nota_final))

    try:
        return ficha.model_copy(update={"nota_a1": nota_final})
    except ValidationError:
        # Fallback defensivo — aplica cap sobre a nota bruta.
        fallback = (
            min(nota_bruta, CAP_NOTA_FORA_DO_TOP)
            if (nota_bruta is not None and ficha.ra not in top_ras)
            else nota_bruta
        )
        return ficha.model_copy(update={"nota_a1": fallback})


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------


def calibrar_batch(
    fichas: list[FichaCorrecao],
    metadata: dict[str, Any],
    client: Any = None,
) -> list[FichaCorrecao]:
    """Calibra as notas do batch aplicando top 10% + cap 9.

    Args:
        fichas: lista de :class:`FichaCorrecao` produzida pelo
            ``batch_processor`` (Story 2.2).
        metadata: metadados do batch (turma, professor, etc.) — repassado
            para fins de log e telemetria. Não é enviado ao Sonnet.
        client: cliente Anthropic já instanciado (injetado para testes).
            Quando ``None``, instancia-se ``anthropic.Anthropic()`` —
            usa ``ANTHROPIC_API_KEY`` do ambiente.

    Returns:
        Lista de :class:`FichaCorrecao` com ``nota_a1`` calibrada,
        preservando a ordem original do batch.

    Note:
        - Batch vazio retorna ``[]`` sem chamar a API (guard).
        - Custo da chamada Sonnet já está contabilizado pelo
          ``batch_processor.estimar_custo_brl`` — :class:`OrcamentoExcedidoError`
          NÃO é levantado aqui.
        - Payload ao Sonnet contém apenas RA + nota (sem nomes, sem texto
          dos trabalhos) — ADR-004.
    """
    if not fichas:
        return []

    total = len(fichas)
    top_n = _calcular_top_n(total)
    top_ras = _identificar_top_ras(fichas, top_n)

    # ADR-004 — payload sem PII (sem nomes, sem RA exposto no log)
    _safe_log_action(
        "inicio_calibracao",
        f"batch de {total} alunos, 1 chamada Sonnet",
    )

    user_message = _montar_payload_sonnet(fichas, top_ras)

    # Lazy import: anthropic é dependência opcional em ambientes de teste
    # (testes sempre injetam ``client`` via fixture/MagicMock).
    if client is None:
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic()

    # V9 ADR-002 — cache_control ephemeral no system prompt
    # V6 ADR-002 — timeout explícito
    # ADR-003 — model Sonnet, temperature=0, max_tokens=4096
    response = client.messages.create(
        model=MODELO_CALIBRACAO,
        max_tokens=MAX_TOKENS_CALIBRACAO,
        temperature=TEMPERATURE_CALIBRACAO,
        timeout=API_TIMEOUT,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT_CALIBRACAO,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    # Tolerante a respostas vazias — ``content`` pode ser lista vazia se o
    # Sonnet abortar precocemente; nesse caso, ``ajustes`` fica vazio e o
    # merge final aplica apenas o cap 9 sobre as notas brutas.
    raw_text = ""
    content_blocks = getattr(response, "content", None) or []
    if content_blocks:
        primeiro = content_blocks[0]
        raw_text = getattr(primeiro, "text", "") or ""

    ajustes = _parse_resposta_sonnet(raw_text)

    # Preserva a ordem original do batch.
    return [_aplicar_calibracao(f, ajustes, top_ras) for f in fichas]


# ---------------------------------------------------------------------------
# Helper de log tolerante (replica padrão do batch_processor)
# ---------------------------------------------------------------------------


def _safe_log_action(acao: str, payload_resumido: str = "") -> None:
    """Wrapper sobre ``log_action()`` tolerante a ausência de Streamlit.

    Em testes unitários ``st.session_state`` pode não existir — preferimos
    silenciar falhas de log a abortar a calibração do batch.
    """
    with contextlib.suppress(Exception):
        log_action(acao=acao, payload_resumido=payload_resumido)
