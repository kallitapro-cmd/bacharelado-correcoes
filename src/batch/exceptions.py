"""Exceções customizadas do orquestrador de batch (Story 2.2).

Define erros levantados pelo ``batch_processor`` quando guardrails arquiteturais
(ADR-005 — política de orçamento) são violados antes de qualquer chamada à API.
"""

from __future__ import annotations


class OrcamentoExcedidoError(Exception):
    """Levantada quando o custo estimado excede ``MAX_COST_BRL`` (ADR-005).

    Esta exceção é levantada ANTES de qualquer chamada à API Anthropic — o
    bloqueio é preventivo e nenhuma cobrança é incorrida.

    Attributes:
        estimativa_brl: custo estimado calculado pela fórmula do ADR-005.
        limite_brl: hard limit configurado em ``MAX_COST_BRL``.
        excesso_brl: ``estimativa_brl - limite_brl``.
    """

    def __init__(self, estimativa_brl: float, limite_brl: float) -> None:
        self.estimativa_brl = estimativa_brl
        self.limite_brl = limite_brl
        self.excesso_brl = estimativa_brl - limite_brl
        super().__init__(
            "ORÇAMENTO EXCEDIDO (ADR-005)\n"
            f"Custo estimado: R$ {estimativa_brl:.2f}\n"
            f"Hard limit (MAX_COST_BRL): R$ {limite_brl:.2f}\n"
            f"Excesso: R$ {self.excesso_brl:.2f}\n"
            "Ajuste MAX_COST_BRL em st.secrets ou reduza o tamanho do batch "
            "antes de tentar novamente."
        )
