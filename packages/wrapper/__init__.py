"""Pacote wrapper — integração com o squad corretor-academico (ADR-002)."""

from packages.wrapper.clone_client import (
    BATCH_SIZE,
    build_system_prompt,
    corrigir_aluno,
)
from packages.wrapper.exceptions import (
    ClonTruncatedResponseError,
    ClonValidationError,
    EmptySquadFileError,
)
from packages.wrapper.schemas import FichaCorrecao, MatrizPontuacao, RespostaBatch

__all__ = [
    "BATCH_SIZE",
    "build_system_prompt",
    "corrigir_aluno",
    "ClonTruncatedResponseError",
    "ClonValidationError",
    "EmptySquadFileError",
    "FichaCorrecao",
    "MatrizPontuacao",
    "RespostaBatch",
]
