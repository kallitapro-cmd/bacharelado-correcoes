"""Cliente Anthropic — wrapper mínimo para conectividade e modelos (Story 1.4).

Este módulo expõe um wrapper mínimo em torno do SDK ``anthropic`` para:

1. Centralizar a configuração da API key (obtida via ``st.secrets`` em produção
   e via variável de ambiente ``ANTHROPIC_API_KEY`` em ambientes de teste/CI).
2. Documentar os modelos definidos no ADR-003 (``claude-haiku-4-5-20251001``
   para batch e ``claude-sonnet-4-6`` para calibração/revisão).
3. Oferecer ``test_connection()`` para validar conectividade e disponibilidade
   do modelo antes de iniciar pipelines pesados (Sprint 2+).

Tratamento de erros segue ADR-002: nunca expor stack trace cru ao usuário e
nunca logar a API key (ADR-004 — ver Story 1.11 para safe_logger).
"""

from __future__ import annotations

import os

import anthropic
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Modelos (ADR-003)
# ---------------------------------------------------------------------------

#: Modelo padrão usado em batch — relação custo/performance.
MODEL_BATCH: str = "claude-haiku-4-5-20251001"

#: Modelo usado em calibração e revisão (maior capacidade).
MODEL_REVIEW: str = "claude-sonnet-4-6"

#: Limite de tokens de saída global (ADR-003).
MAX_TOKENS: int = 4096

#: Temperatura usada em chamadas de teste/determinismo (ADR-003).
TEST_TEMPERATURE: float = 0.0


# ---------------------------------------------------------------------------
# Erros internos
# ---------------------------------------------------------------------------


class APIClientError(RuntimeError):
    """Erro de uso do cliente Anthropic (mensagem human-readable).

    Esta exceção encapsula falhas conhecidas (autenticação, conectividade,
    configuração ausente) com mensagens claras. Nunca contém a API key ou
    qualquer fragmento dela.
    """


# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------


def _resolve_api_key() -> str:
    """Resolve a API key a partir de ``st.secrets`` ou variável de ambiente.

    Ordem de resolução:

    1. ``st.secrets["ANTHROPIC_API_KEY"]`` (produção via Streamlit).
    2. ``os.environ["ANTHROPIC_API_KEY"]`` (CI / desenvolvimento local).

    Returns:
        A API key como string não-vazia.

    Raises:
        APIClientError: se a key não estiver disponível em nenhuma das fontes.
    """
    # Tenta Streamlit secrets primeiro (somente se streamlit estiver disponível
    # e configurado — caso contrário, cai silenciosamente para env var).
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is not None:
            try:
                value = secrets["ANTHROPIC_API_KEY"]
            except (KeyError, FileNotFoundError, Exception):  # noqa: BLE001
                # Streamlit pode lançar StreamlitSecretNotFoundError ou similar
                # quando secrets.toml não existe — caímos para env var.
                value = None
            if isinstance(value, str) and value.strip():
                return value.strip()
    except ImportError:
        # Streamlit não instalado nesse ambiente — fallback para env var.
        pass

    env_value = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_value:
        return env_value

    raise APIClientError("API key inválida ou ausente. Verifique ANTHROPIC_API_KEY nos secrets.")


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------


def get_client() -> Anthropic:
    """Retorna um cliente Anthropic configurado com a API key dos secrets.

    Returns:
        Instância de :class:`anthropic.Anthropic` pronta para uso.

    Raises:
        APIClientError: se a API key não estiver disponível. A mensagem é
            human-readable e não contém qualquer parte da key.
    """
    api_key = _resolve_api_key()
    return Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Teste de conectividade
# ---------------------------------------------------------------------------


def test_connection(model: str = MODEL_BATCH) -> bool:
    """Testa conectividade com a API Anthropic e o modelo informado.

    Faz uma chamada mínima ao endpoint ``messages.create`` com ``temperature=0``
    e prompt curto. Retorna ``True`` se a resposta vier não-vazia.

    Args:
        model: Identificador do modelo Anthropic a testar. Por padrão,
            ``MODEL_BATCH`` (``claude-haiku-4-5-20251001``).

    Returns:
        ``True`` se a chamada retornou conteúdo de texto não-vazio.

    Raises:
        APIClientError: em caso de autenticação inválida, sem conectividade
            ou outras falhas conhecidas da API. A mensagem é human-readable
            e nunca contém a API key.
    """
    client = get_client()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            temperature=TEST_TEMPERATURE,
            messages=[
                {
                    "role": "user",
                    "content": "Diga 'ok' em uma palavra.",
                }
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise APIClientError(
            "API key inválida ou ausente. Verifique ANTHROPIC_API_KEY nos secrets."
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise APIClientError(
            "Sem conectividade com a API Anthropic. Verifique sua conexão."
        ) from exc
    except anthropic.APIStatusError as exc:
        # Erros HTTP da API (rate limit, server error, etc.) — mensagem genérica
        # sem expor headers/body que possam conter detalhes sensíveis.
        raise APIClientError(
            f"Erro ao chamar a API Anthropic (status {exc.status_code}). "
            "Tente novamente em alguns instantes."
        ) from exc
    except anthropic.AnthropicError as exc:
        # Catch-all para qualquer outro erro do SDK — mensagem genérica.
        raise APIClientError(
            "Falha inesperada ao chamar a API Anthropic. Verifique configuração."
        ) from exc

    # Extrai texto da resposta — formato: response.content é List[ContentBlock]
    content_blocks = getattr(response, "content", None) or []
    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return True

    return False
