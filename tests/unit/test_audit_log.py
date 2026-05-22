"""Testes unitários para audit log de sessão — Story 1.12.

Estes testes mockam ``streamlit.session_state`` como um ``dict`` simples
para que possam rodar fora do runtime do Streamlit. O módulo
``src.utils.audit_log`` lê e escreve em ``st.session_state`` em tempo
de chamada (não em import time), o que permite injetar o mock por meio
de :func:`unittest.mock.patch`.
"""

from __future__ import annotations

import csv
import io
import unittest.mock as mock
from datetime import datetime
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


# As 7 ações obrigatórias do AC #1.
ACOES_OBRIGATORIAS: tuple[str, ...] = (
    "login",
    "upload",
    "inicio_batch",
    "aprovacao_linha",
    "edicao_nota",
    "rejeicao_regeneracao",
    "exportacao",
)


# --- Helpers ----------------------------------------------------------------


def _log_from(session: dict[str, object]) -> list[dict[str, str]]:
    """Recupera o audit log do fake session_state já com o tipo refinado."""

    from src.utils.audit_log import AUDIT_LOG_KEY

    return cast("list[dict[str, str]]", session[AUDIT_LOG_KEY])


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def fake_session() -> Iterator[dict[str, object]]:
    """Mocka ``streamlit.session_state`` como dict simples por teste.

    Cria um dict isolado, faz patch em ``streamlit.session_state`` e
    devolve a referência para o teste poder inspecionar/injetar valores
    diretamente (ex.: ``fake_session['identificacao_pa'] = 'Prof. X'``).
    """

    session: dict[str, object] = {}
    with mock.patch("streamlit.session_state", session):
        yield session


# --- AC #1 — todas as 7 ações geram entrada no log --------------------------


class TestAcoesObrigatorias:
    """AC #1: cada ação listada gera uma entrada no audit log."""

    @pytest.mark.parametrize("acao", ACOES_OBRIGATORIAS)
    def test_acao_individual_gera_entrada(self, fake_session: dict[str, object], acao: str) -> None:
        from src.utils.audit_log import log_action

        log_action(acao, "payload sem PII")

        log = _log_from(fake_session)
        assert len(log) == 1
        entrada = log[0]
        assert entrada["acao"] == acao
        assert entrada["payload_resumido"] == "payload sem PII"

    def test_todas_as_acoes_em_sequencia(self, fake_session: dict[str, object]) -> None:
        from src.utils.audit_log import log_action

        payloads = {
            "login": "login bem-sucedido",
            "upload": "planilha carregada: 32 alunos",
            "inicio_batch": "batch iniciado: lote 1/3, 10 alunos",
            "aprovacao_linha": "linha aprovada: lote 2, posição 5",
            "edicao_nota": "nota editada: lote 1, posição 3",
            "rejeicao_regeneracao": "regeneração solicitada: lote 2, posição 8",
            "exportacao": "planilha exportada: 32 fichas",
        }

        for acao, payload in payloads.items():
            log_action(acao, payload)

        log = _log_from(fake_session)
        assert len(log) == len(ACOES_OBRIGATORIAS)
        acoes_registradas = [entrada["acao"] for entrada in log]
        assert acoes_registradas == list(payloads.keys())


# --- AC #1.b — estrutura da entrada -----------------------------------------


class TestEstruturaEntrada:
    """Cada entrada deve conter os 4 campos obrigatórios."""

    def test_entrada_contem_quatro_campos(self, fake_session: dict[str, object]) -> None:
        from src.utils.audit_log import log_action

        log_action("login", "ok")

        entrada = _log_from(fake_session)[0]
        assert set(entrada.keys()) == {
            "timestamp",
            "identificacao_pa",
            "acao",
            "payload_resumido",
        }

    def test_timestamp_e_iso_8601_utc(self, fake_session: dict[str, object]) -> None:
        from src.utils.audit_log import log_action

        log_action("login", "ok")

        timestamp = _log_from(fake_session)[0]["timestamp"]
        # datetime.fromisoformat aceita o formato gerado por isoformat().
        parsed = datetime.fromisoformat(timestamp)
        offset = parsed.utcoffset()
        assert offset is not None, "timestamp deve incluir timezone"
        # offset zero == UTC.
        assert offset.total_seconds() == 0

    def test_identificacao_pa_default_quando_nao_definido(
        self, fake_session: dict[str, object]
    ) -> None:
        from src.utils.audit_log import log_action

        # session_state vazio — sem identificacao_pa.
        log_action("login", "ok")

        entrada = _log_from(fake_session)[0]
        assert entrada["identificacao_pa"] == "desconhecido"

    def test_identificacao_pa_capturada_quando_definida(
        self, fake_session: dict[str, object]
    ) -> None:
        from src.utils.audit_log import log_action

        fake_session["identificacao_pa"] = "Prof. Ana"
        log_action("login", "ok")

        entrada = _log_from(fake_session)[0]
        assert entrada["identificacao_pa"] == "Prof. Ana"


# --- AC #2 — get_csv produz CSV utilizável pelo st.download_button ----------


class TestGetCsv:
    """``get_csv`` retorna bytes UTF-8 com cabeçalho + linhas."""

    def test_csv_vazio_contem_apenas_cabecalho(
        self,
        fake_session: dict[str, object],  # noqa: ARG002
    ) -> None:
        from src.utils.audit_log import get_csv

        csv_bytes = get_csv()
        assert isinstance(csv_bytes, bytes)
        texto = csv_bytes.decode("utf-8")
        linhas = [linha for linha in texto.splitlines() if linha]
        assert linhas == ["timestamp,identificacao_pa,acao,payload_resumido"]

    def test_csv_contem_todas_as_acoes_registradas(
        self,
        fake_session: dict[str, object],  # noqa: ARG002
    ) -> None:
        from src.utils.audit_log import get_csv, log_action

        for acao in ACOES_OBRIGATORIAS:
            log_action(acao, f"{acao} payload")

        csv_bytes = get_csv()
        texto = csv_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(texto))
        registros = list(reader)
        assert len(registros) == len(ACOES_OBRIGATORIAS)
        acoes_no_csv = [r["acao"] for r in registros]
        assert acoes_no_csv == list(ACOES_OBRIGATORIAS)

    def test_csv_encoding_e_utf8(
        self,
        fake_session: dict[str, object],  # noqa: ARG002
    ) -> None:
        from src.utils.audit_log import get_csv, log_action

        # Usa acento para garantir que UTF-8 está preservado.
        log_action("aprovacao_linha", "regeneração concluída")
        csv_bytes = get_csv()
        # decode em utf-8 não deve disparar exceção.
        texto = csv_bytes.decode("utf-8")
        assert "regeneração concluída" in texto


# --- AC #3 — ausência de PII no log -----------------------------------------


class TestSemPIINoLog:
    """AC #3: log NÃO deve conter RA, nome ou nota de aluno (ADR-004)."""

    def test_log_completo_sem_ra_padrao_11_digitos(
        self,
        fake_session: dict[str, object],  # noqa: ARG002
    ) -> None:
        """RA é um número de 11 dígitos — não deve aparecer no payload.

        Este teste documenta que cabe ao **chamador** garantir que o
        ``payload_resumido`` é agregado. Aqui validamos que os payloads
        recomendados na story (Notas Técnicas) não vazam PII.
        """

        from src.utils.audit_log import get_csv, log_action

        payloads_agregados = [
            ("login", "login bem-sucedido"),
            ("upload", "planilha carregada: 32 alunos"),
            ("inicio_batch", "batch iniciado: lote 1/3, 10 alunos"),
            ("aprovacao_linha", "linha aprovada: lote 2, posição 5"),
            ("edicao_nota", "nota editada: lote 1, posição 3"),
            ("rejeicao_regeneracao", "regeneração solicitada: lote 2, posição 8"),
            ("exportacao", "planilha exportada: 32 fichas"),
        ]

        for acao, payload in payloads_agregados:
            log_action(acao, payload)

        texto = get_csv().decode("utf-8")

        # Não pode conter RA (11 dígitos consecutivos).
        import re

        assert re.search(r"\b\d{11}\b", texto) is None, (
            "RA detectado no audit log — violação ADR-004"
        )

        # Termos PII proibidos não devem aparecer literalmente.
        termos_proibidos = ("RA:", "ra=", "Nome:", "nota=", "Nota:")
        for termo in termos_proibidos:
            assert termo not in texto, f"Termo PII '{termo}' encontrado no log"

    def test_csv_de_log_vazio_nao_contem_pii(
        self,
        fake_session: dict[str, object],  # noqa: ARG002
    ) -> None:
        from src.utils.audit_log import get_csv

        texto = get_csv().decode("utf-8")
        # Cabeçalho lista apenas os 4 campos esperados — nenhum contém PII.
        cabecalho = texto.splitlines()[0]
        assert "RA" not in cabecalho
        assert "nome" not in cabecalho.lower()
        assert "nota" not in cabecalho.lower()


# --- AC #4 — log é zerado e clear_log funciona ------------------------------


class TestClearLog:
    """AC #4 + função utilitária ``clear_log``."""

    def test_clear_log_remove_todas_as_entradas(self, fake_session: dict[str, object]) -> None:
        from src.utils.audit_log import AUDIT_LOG_KEY, clear_log, log_action

        log_action("login", "ok")
        log_action("upload", "ok")
        assert len(_log_from(fake_session)) == 2

        clear_log()
        assert fake_session[AUDIT_LOG_KEY] == []

    def test_clear_log_idempotente_em_log_vazio(self, fake_session: dict[str, object]) -> None:
        from src.utils.audit_log import AUDIT_LOG_KEY, clear_log

        clear_log()
        clear_log()
        assert fake_session[AUDIT_LOG_KEY] == []

    def test_log_nao_persiste_entre_sessoes_simuladas(self) -> None:
        """Cada sessão simulada é um dict novo — simulando sessão Streamlit nova."""

        from src.utils.audit_log import AUDIT_LOG_KEY, get_csv, log_action

        # Sessão 1.
        sessao_1: dict[str, object] = {}
        with mock.patch("streamlit.session_state", sessao_1):
            log_action("login", "ok")
            assert len(_log_from(sessao_1)) == 1

        # Sessão 2 — começa do zero.
        sessao_2: dict[str, object] = {}
        with mock.patch("streamlit.session_state", sessao_2):
            texto = get_csv().decode("utf-8")
            linhas = [linha for linha in texto.splitlines() if linha]
            # Apenas o cabeçalho — sem traços da sessão 1.
            assert linhas == ["timestamp,identificacao_pa,acao,payload_resumido"]
            assert AUDIT_LOG_KEY in sessao_2
            assert sessao_2[AUDIT_LOG_KEY] == []
