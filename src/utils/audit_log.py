"""Audit log de sessão para o Corretor Acadêmico (Story 1.12).

Registra ações do Professor Auxiliar (PA) em ``st.session_state``, sem
qualquer persistência fora da sessão Streamlit. O log é zerado quando o
browser ou a sessão termina (retenção zero conforme ADR-004).

Campos registrados:

- ``timestamp``: ISO 8601 em UTC (ex.: ``2026-05-22T13:45:12.345678+00:00``).
- ``identificacao_pa``: nome informado pelo PA no login (Story 1.2).
- ``acao``: ação realizada (ex.: ``login``, ``upload``, ``exportacao``).
- ``payload_resumido``: descrição agregada da ação **sem PII de alunos**.

Importante (ADR-004): ``payload_resumido`` **NÃO** deve conter nomes,
RAs ou notas de alunos. Use resumos agregados como
``"lote 2, 15 alunos"``. A responsabilidade de não vazar PII é do
chamador — este módulo apenas armazena e exporta o que recebe.

O CSV produzido por :func:`get_csv` é destinado ao :func:`st.download_button`
na sidebar do ``app.py``, permitindo que o PA baixe o log antes de
encerrar a sessão para fins de auditoria institucional.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Final, cast

import streamlit as st

#: Chave usada em :data:`streamlit.session_state` para armazenar o log.
AUDIT_LOG_KEY: Final[str] = "audit_log"

#: Chave usada para recuperar a identificação do PA (Story 1.2).
_IDENTIFICACAO_PA_KEY: Final[str] = "identificacao_pa"

#: Valor exibido no log quando a identificação do PA não está disponível.
_IDENTIFICACAO_PA_DEFAULT: Final[str] = "desconhecido"

#: Ordem dos campos do CSV — mantida estável para auditoria.
CSV_FIELDS: Final[tuple[str, ...]] = (
    "timestamp",
    "identificacao_pa",
    "acao",
    "payload_resumido",
)


def _get_log() -> list[dict[str, str]]:
    """Retorna a lista de entradas do audit log da sessão atual.

    Garante que a chave existe em ``st.session_state`` antes de retornar
    — o que permite chamar :func:`log_action` sem inicialização prévia.
    """

    if AUDIT_LOG_KEY not in st.session_state:
        st.session_state[AUDIT_LOG_KEY] = []
    return cast("list[dict[str, str]]", st.session_state[AUDIT_LOG_KEY])


def log_action(acao: str, payload_resumido: str = "") -> None:
    """Registra uma ação do PA no audit log de sessão.

    Args:
        acao: rótulo da ação executada. As ações esperadas pelo Sprint 1
            são: ``login``, ``upload``, ``inicio_batch``, ``aprovacao_linha``,
            ``edicao_nota``, ``rejeicao_regeneracao``, ``exportacao``.
        payload_resumido: descrição agregada (sem PII de alunos).

    IMPORTANTE (ADR-004): ``payload_resumido`` **NÃO** deve conter nomes
    de alunos, RAs individuais ou notas. Use resumos como
    ``"lote 2, 15 alunos"``.
    """

    entrada: dict[str, str] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "identificacao_pa": str(
            st.session_state.get(_IDENTIFICACAO_PA_KEY, _IDENTIFICACAO_PA_DEFAULT)
        ),
        "acao": acao,
        "payload_resumido": payload_resumido,
    }
    _get_log().append(entrada)


def get_csv() -> bytes:
    """Serializa o audit log da sessão como CSV UTF-8 para download.

    Returns:
        Bytes do CSV em UTF-8 com cabeçalho. Quando o log está vazio,
        retorna apenas a linha de cabeçalho para que o arquivo continue
        sendo um CSV válido.
    """

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(CSV_FIELDS))
    writer.writeheader()
    writer.writerows(_get_log())
    return output.getvalue().encode("utf-8")


def clear_log() -> None:
    """Zera o audit log da sessão atual.

    Útil em testes e em fluxos que precisam reiniciar a auditoria
    explicitamente; em condições normais, o log já é descartado quando
    a sessão Streamlit termina.
    """

    st.session_state[AUDIT_LOG_KEY] = []
