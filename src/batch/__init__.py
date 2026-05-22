"""Pacote ``src.batch`` — orquestrador e estado intermediário do batch de correção.

Exporta os símbolos públicos do orquestrador (Story 2.2) e mantém o módulo
``batch_state`` (Story 2.6) como infraestrutura de persistência efêmera.
"""

from __future__ import annotations

from src.batch.batch_processor import (
    AcaoBatch,
    estimar_custo_brl,
    processar_batch,
)
from src.batch.exceptions import OrcamentoExcedidoError

__all__ = [
    "AcaoBatch",
    "OrcamentoExcedidoError",
    "estimar_custo_brl",
    "processar_batch",
]
