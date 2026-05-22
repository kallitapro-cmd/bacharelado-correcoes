"""Normalização do RA do aluno (Story 1.10, ADR-001)."""

from __future__ import annotations

import re


def normalize_ra(raw: str) -> str:
    """Normaliza um Registro Acadêmico (RA) para o formato canônico de 11 dígitos.

    Regra (ADR-001):
    - Remove formatação não-numérica (pontos, hífens, barras) antes de normalizar.
    - 11 dígitos          → retorna como está (bypass)
    - 10 dígitos + prefixo 2025/2026 → insere '0' na posição 4 (após o ano)
    - Outros formatos     → retorna como está (Camada 3 — revisão manual)

    IMPORTANTE: NUNCA usar zfill(11) — produz resultado inválido (ADR-001).
    """
    ra = re.sub(r"[^\d]", "", str(raw).strip())
    if len(ra) == 10 and (ra.startswith("2025") or ra.startswith("2026")):
        return ra[:4] + "0" + ra[4:]
    return ra
