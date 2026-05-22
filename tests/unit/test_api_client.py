"""Testes unitários para api_client — Story 1.4.

Os testes de conectividade real (que fazem chamada HTTP à API Anthropic) são
marcados com ``@pytest.mark.skipif`` e só rodam quando ``ANTHROPIC_API_KEY``
está no ambiente. Os testes de tratamento de erro usam ``unittest.mock`` para
simular as exceções do SDK sem depender de rede.

Modelos testados (ADR-003):
- ``claude-haiku-4-5-20251001`` — padrão para batch.
- ``claude-sonnet-4-6`` — calibração/revisão.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from src.utils.api_client import (
    MAX_TOKENS,
    MODEL_BATCH,
    MODEL_REVIEW,
    TEST_TEMPERATURE,
    APIClientError,
    get_client,
)
from src.utils.api_client import test_connection as check_connection

# ---------------------------------------------------------------------------
# Constantes / fixtures
# ---------------------------------------------------------------------------


HAS_REAL_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _fake_message_response(text: str) -> MagicMock:
    """Constrói um objeto que mimetiza ``Message`` do SDK Anthropic."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


# ---------------------------------------------------------------------------
# Constantes do módulo
# ---------------------------------------------------------------------------


class TestConstantes:
    def test_model_batch_e_claude_haiku(self) -> None:
        assert MODEL_BATCH == "claude-haiku-4-5-20251001"

    def test_model_review_e_claude_sonnet(self) -> None:
        assert MODEL_REVIEW == "claude-sonnet-4-6"

    def test_max_tokens_e_4096(self) -> None:
        assert MAX_TOKENS == 4096

    def test_temperatura_de_teste_e_zero(self) -> None:
        assert TEST_TEMPERATURE == 0.0


# ---------------------------------------------------------------------------
# get_client()
# ---------------------------------------------------------------------------


class TestGetClient:
    def test_retorna_instancia_anthropic_com_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")
        # Garante que streamlit secrets não interfira (não existe secrets.toml).
        client = get_client()
        assert isinstance(client, anthropic.Anthropic)

    def test_sem_api_key_lanca_api_client_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("src.utils.api_client._resolve_api_key") as mock_resolve:
            mock_resolve.side_effect = APIClientError(
                "API key inválida ou ausente. Verifique ANTHROPIC_API_KEY nos secrets."
            )
            with pytest.raises(APIClientError, match="API key inválida ou ausente"):
                get_client()


# ---------------------------------------------------------------------------
# check_connection() — comportamento com mocks
# ---------------------------------------------------------------------------


class TestTestConnectionComMocks:
    def test_resposta_valida_retorna_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")
        fake_response = _fake_message_response("ok")

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            assert check_connection() is True

            mock_client.messages.create.assert_called_once()
            _, kwargs = mock_client.messages.create.call_args
            assert kwargs["model"] == MODEL_BATCH
            assert kwargs["temperature"] == TEST_TEMPERATURE
            assert kwargs["max_tokens"] == MAX_TOKENS

    def test_resposta_vazia_retorna_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")
        fake_response = _fake_message_response("   ")  # apenas whitespace

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            assert check_connection() is False

    def test_content_sem_blocos_retorna_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")
        response = MagicMock()
        response.content = []

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = response
            mock_anthropic_cls.return_value = mock_client

            assert check_connection() is False

    def test_authentication_error_lanca_api_client_error_com_mensagem_clara(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-invalida")

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 401
            mock_response.headers = {}
            mock_client.messages.create.side_effect = anthropic.AuthenticationError(
                message="invalid api key",
                response=mock_response,
                body={"error": {"message": "invalid"}},
            )
            mock_anthropic_cls.return_value = mock_client

            with pytest.raises(APIClientError) as exc_info:
                check_connection()

            assert "API key inválida ou ausente" in str(exc_info.value)
            # Garante que a mensagem NÃO contém a API key.
            assert "sk-ant-invalida" not in str(exc_info.value)

    def test_api_connection_error_lanca_api_client_error_com_mensagem_clara(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_request = MagicMock(spec=httpx.Request)
            mock_client.messages.create.side_effect = anthropic.APIConnectionError(
                request=mock_request
            )
            mock_anthropic_cls.return_value = mock_client

            with pytest.raises(APIClientError, match="Sem conectividade"):
                check_connection()

    def test_api_status_error_lanca_api_client_error_generico(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 500
            mock_response.headers = {}
            mock_client.messages.create.side_effect = anthropic.APIStatusError(
                message="server error",
                response=mock_response,
                body=None,
            )
            mock_anthropic_cls.return_value = mock_client

            with pytest.raises(APIClientError) as exc_info:
                check_connection()

            assert "Erro ao chamar a API Anthropic" in str(exc_info.value)
            assert "500" in str(exc_info.value)

    def test_modelo_customizado_e_usado_na_chamada(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")
        fake_response = _fake_message_response("ok")

        with patch("src.utils.api_client.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            assert check_connection(model=MODEL_REVIEW) is True

            _, kwargs = mock_client.messages.create.call_args
            assert kwargs["model"] == MODEL_REVIEW


# ---------------------------------------------------------------------------
# check_connection() — chamada REAL (somente com API key real disponível)
#
# Estes testes documentam que ambos os modelos do ADR-003 respondem.
# Pulados automaticamente em ambientes sem ANTHROPIC_API_KEY (CI sem secret).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_REAL_API_KEY,
    reason="ANTHROPIC_API_KEY não disponível — teste de conectividade real ignorado.",
)
class TestTestConnectionReal:
    def test_haiku_responde(self) -> None:
        """Chamada real ao modelo claude-haiku-4-5-20251001 (batch)."""
        assert check_connection(model=MODEL_BATCH) is True

    def test_sonnet_responde(self) -> None:
        """Chamada real ao modelo claude-sonnet-4-6 (review/calibração)."""
        assert check_connection(model=MODEL_REVIEW) is True
