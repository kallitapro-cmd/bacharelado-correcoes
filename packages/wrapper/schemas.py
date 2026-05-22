"""Schemas Pydantic da resposta da IA — Wrapper Python (ADR-002).

Copiados exatamente da seção "Schema de Resposta" do ADR-002.
NÃO alterar campos sem atualizar o ADR.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MatrizPontuacao(BaseModel):
    """Pontuação por critério extraído do enunciado (H2)."""

    criterio_apresentacao: float | None = Field(None, ge=0.0, le=10.0)
    criterio_conteudo: float | None = Field(None, ge=0.0, le=10.0)
    criterio_metodologia: float | None = Field(None, ge=0.0, le=10.0)
    criterio_conclusao: float | None = Field(None, ge=0.0, le=10.0)


class FichaCorrecao(BaseModel):
    """Ficha individual de correção para um aluno (ADR-002)."""

    ra: str = Field(..., pattern=r"^\d{11}$", description="RA normalizado 11 dígitos")
    nota_a1: float | None = Field(None, ge=0.0, le=10.0)
    nota_a2: float | None = Field(None, ge=0.0, le=10.0)
    matriz_pontuacao: MatrizPontuacao | None = None
    feedback: str = Field(..., min_length=1)
    flags: list[
        Literal[
            "plagio",
            "ia_generativa",
            "arquivo_errado",
            "sem_vinculo",
            "possivel_injection",  # V5
        ]
    ] = Field(default_factory=list)
    confianca: Literal["alta", "media", "baixa"]

    @field_validator("ra")
    @classmethod
    def normaliza_ra(cls, v: str) -> str:
        return v.strip()


class RespostaBatch(BaseModel):
    """Resposta consolidada para um batch de correções (ADR-002).

    min_length=1 garante que a IA sempre retorne ao menos uma ficha.
    """

    fichas: list[FichaCorrecao] = Field(..., min_length=1)
    observacoes_gerais: str | None = Field(None)
