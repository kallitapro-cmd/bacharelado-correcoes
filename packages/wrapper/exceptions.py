"""Exceções customizadas do Wrapper Python (ADR-002)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


class EmptySquadFileError(Exception):
    """Levantada quando um arquivo do squad existe mas está vazio após strip (V4)."""


class ClonValidationError(Exception):
    """Levantada após esgotar tentativas de validação Pydantic (V2).

    Atributos:
        raw: resposta bruta da IA que falhou validação.
        errors: lista de erros Pydantic reportados (formato `ErrorDetails`).
    """

    def __init__(self, raw: str, errors: Sequence[Any]) -> None:
        self.raw = raw
        self.errors = errors
        super().__init__(f"Validação falhou após 2 tentativas. raw[:200]={raw[:200]!r}")


class ClonTruncatedResponseError(Exception):
    """Levantada quando stop_reason == 'max_tokens' (V3).

    Atributos:
        ra: RA do primeiro aluno do batch afetado (pode ser None).
        tokens_used: tokens de output consumidos na chamada.
    """

    def __init__(self, ra: str | None, tokens_used: int) -> None:
        self.ra = ra
        self.tokens_used = tokens_used
        super().__init__(f"Resposta truncada por max_tokens (ra={ra}, tokens_used={tokens_used})")
