"""Testes unitários para safe_logger — Story 1.11."""

from __future__ import annotations

import io
import logging
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from src.utils.logger import (
    PATTERNS,
    SanitizingFilter,
    get_safe_logger,
    safe_logger,
    sanitize,
)


@pytest.fixture()
def captured_logger() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """Cria logger isolado com handler StringIO para captura de saída."""
    stream = io.StringIO()
    # Nome único garante isolamento entre testes (sem reaproveitar handlers).
    name = f"test_safe_logger_{uuid.uuid4().hex}"
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.addFilter(SanitizingFilter())
    logger.addHandler(handler)
    try:
        yield logger, stream
    finally:
        logger.removeHandler(handler)
        handler.close()


def _capture_log(
    logger: logging.Logger,
    stream: io.StringIO,
    level: str,
    message: str,
    *args: object,
) -> str:
    getattr(logger, level)(message, *args)
    for handler in logger.handlers:
        handler.flush()
    return stream.getvalue().strip()


class TestSanitizeFunction:
    """Testa a função sanitize() diretamente, sem o logger."""

    def test_ra_11_digitos_substituido(self) -> None:
        assert sanitize("RA: 20260100418") == "RA: [RA_REDACTED]"

    def test_ra_no_meio_do_texto(self) -> None:
        resultado = sanitize("Aluno 20260100418 entregou tarefa")
        assert "20260100418" not in resultado
        assert "[RA_REDACTED]" in resultado

    def test_api_key_anthropic_substituida(self) -> None:
        resultado = sanitize("key=sk-ant-api03-XyZ_abc-123")
        assert "[API_KEY_REDACTED]" in resultado
        assert "sk-ant-api03-XyZ_abc-123" not in resultado

    def test_mensagem_sem_dados_sensiveis_preservada(self) -> None:
        msg = "Processamento iniciado para 5 alunos"
        assert sanitize(msg) == msg

    def test_multiplos_padroes_na_mesma_mensagem(self) -> None:
        msg = "RA 20260100418 com chave sk-ant-api03-segredo"
        resultado = sanitize(msg)
        assert "[RA_REDACTED]" in resultado
        assert "[API_KEY_REDACTED]" in resultado
        assert "20260100418" not in resultado
        assert "sk-ant-api03-segredo" not in resultado

    def test_string_vazia_e_idempotente(self) -> None:
        assert sanitize("") == ""

    def test_numero_com_menos_de_11_digitos_nao_redactado(self) -> None:
        # Boundary check: numero com 10 digitos nao deve ser censurado.
        msg = "ID 1234567890 ativo"
        assert sanitize(msg) == msg

    def test_numero_com_mais_de_11_digitos_nao_redactado(self) -> None:
        # \b\d{11}\b exige fronteira de palavra — 12 dígitos não casa.
        msg = "Codigo 123456789012 valido"
        assert sanitize(msg) == msg


class TestSafeLoggerInfo:
    """AC1: safe_logger.info não grava RAs."""

    def test_ra_redacted_no_log_info(
        self, captured_logger: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, stream = captured_logger
        saida = _capture_log(logger, stream, "info", "RA do aluno: 20260100418")
        assert "[RA_REDACTED]" in saida
        assert "20260100418" not in saida


class TestSafeLoggerError:
    """AC2: safe_logger.error não grava API keys."""

    def test_api_key_redacted_no_log_error(
        self, captured_logger: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, stream = captured_logger
        saida = _capture_log(logger, stream, "error", "Erro com chave: sk-ant-api03-xyz123")
        assert "[API_KEY_REDACTED]" in saida
        assert "sk-ant-api03-xyz123" not in saida


class TestStackTraceSanitization:
    """AC3: stack trace contendo API key é sanitizado."""

    def test_args_tupla_sao_sanitizados(
        self, captured_logger: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, stream = captured_logger
        saida = _capture_log(
            logger,
            stream,
            "error",
            "Falha ao chamar API com %s e aluno %s",
            "sk-ant-api03-segredo",
            "20260100418",
        )
        assert "[API_KEY_REDACTED]" in saida
        assert "[RA_REDACTED]" in saida
        assert "sk-ant-api03-segredo" not in saida
        assert "20260100418" not in saida

    def test_args_dict_sao_sanitizados(
        self, captured_logger: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, stream = captured_logger
        logger.error("Chave: %(key)s RA: %(ra)s", {"key": "sk-ant-api03-x", "ra": "20260100418"})
        for handler in logger.handlers:
            handler.flush()
        saida = stream.getvalue().strip()
        assert "[API_KEY_REDACTED]" in saida
        assert "[RA_REDACTED]" in saida
        assert "sk-ant-api03-x" not in saida
        assert "20260100418" not in saida


class TestSafeMessageUnchanged:
    """AC4: mensagem sem dados sensíveis é gravada normalmente."""

    def test_mensagem_limpa_nao_alterada(
        self, captured_logger: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, stream = captured_logger
        msg = "Processamento iniciado para 5 alunos"
        saida = _capture_log(logger, stream, "info", msg)
        assert saida == msg

    def test_mensagem_com_numero_curto_preservada(
        self, captured_logger: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, stream = captured_logger
        msg = "Total de 42 trabalhos processados"
        saida = _capture_log(logger, stream, "info", msg)
        assert saida == msg


class TestGetSafeLoggerIdempotencia:
    """get_safe_logger() não duplica handlers em chamadas repetidas."""

    def test_chamadas_repetidas_nao_duplicam_handlers(self) -> None:
        nome = f"idempotencia_test_{uuid.uuid4().hex}"
        logger_a = get_safe_logger(nome)
        handlers_inicial = len(logger_a.handlers)
        logger_b = get_safe_logger(nome)
        assert logger_a is logger_b
        assert len(logger_b.handlers) == handlers_inicial

    def test_logger_retornado_tem_filtro_sanitizante(self) -> None:
        nome = f"filter_test_{uuid.uuid4().hex}"
        logger = get_safe_logger(nome)
        handler = logger.handlers[0]
        assert any(isinstance(f, SanitizingFilter) for f in handler.filters)


class TestSafeLoggerSingleton:
    """O safe_logger exposto pelo módulo está configurado corretamente."""

    def test_safe_logger_global_tem_handler_com_filtro(self) -> None:
        assert safe_logger.handlers, "safe_logger deve ter ao menos um handler"
        for handler in safe_logger.handlers:
            assert any(isinstance(f, SanitizingFilter) for f in handler.filters), (
                "Todo handler do safe_logger global deve ter SanitizingFilter"
            )


class TestPatternsRegistry:
    """Garante que a lista PATTERNS contém os padrões esperados."""

    def test_patterns_contem_api_key_e_ra(self) -> None:
        replacements = {replacement for _, replacement in PATTERNS}
        assert "[API_KEY_REDACTED]" in replacements
        assert "[RA_REDACTED]" in replacements
