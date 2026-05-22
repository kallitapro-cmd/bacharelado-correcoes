"""Schemas Pydantic do pipeline de correção (Story 1.9).

Implementa os modelos canônicos do contrato Clone↔Wrapper (ADR-002) e os
modelos adicionais necessários para o estado interno da aplicação.

Referências:
    - ADR-001: formato de RA normalizado (11 dígitos).
    - ADR-002: contrato Clone↔Wrapper (FichaCorrecao, RespostaBatch).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Tipos auxiliares
# ---------------------------------------------------------------------------

FlagCorrecao = Literal["plagio", "ia_generativa", "arquivo_errado", "sem_vinculo"]
"""Conjunto fechado de flags reportáveis pelo Clone (ADR-002)."""

NivelConfianca = Literal["alta", "media", "baixa"]
"""Níveis de confiança da resposta da IA (ADR-002)."""

StatusLote = Literal["pendente", "processando", "concluido", "erro"]
"""Estados possíveis de um lote de processamento."""

StatusBatch = Literal["configurando", "processando", "revisao", "exportado"]
"""Estados possíveis do batch completo."""

MetodoExtracao = Literal["nativo", "ocr", "misto", "nenhum"]
"""Métodos de extração de texto de arquivos de alunos."""

# Regex de data ISO (YYYY-MM-DD) e BR (DD/MM/YYYY)
_RE_DATA_ISO = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
_RE_DATA_BR = re.compile(r"^(?:0[1-9]|[12]\d|3[01])/(?:0[1-9]|1[0-2])/\d{4}$")


def _normaliza_ra(v: str) -> str:
    """Aplica strip ao RA antes da validação por regex."""
    if not isinstance(v, str):
        raise TypeError("ra deve ser string")
    return v.strip()


# ---------------------------------------------------------------------------
# Modelos canônicos do ADR-002
# ---------------------------------------------------------------------------


class MatrizPontuacao(BaseModel):
    """Matriz de critérios de avaliação (ADR-002)."""

    criterio_apresentacao: float | None = Field(default=None, ge=0.0, le=10.0)
    criterio_conteudo: float | None = Field(default=None, ge=0.0, le=10.0)
    criterio_metodologia: float | None = Field(default=None, ge=0.0, le=10.0)
    criterio_conclusao: float | None = Field(default=None, ge=0.0, le=10.0)


class FichaCorrecao(BaseModel):
    """Ficha de correção individual por aluno (ADR-002).

    Campos obrigatórios: ``ra``, ``feedback``, ``confianca``.
    Campos opcionais: notas e matriz de pontuação.
    """

    ra: str = Field(
        ...,
        pattern=r"^\d{11}$",
        description="RA normalizado 11 dígitos (ADR-001)",
    )
    nota_a1: float | None = Field(default=None, ge=0.0, le=10.0)
    nota_a2: float | None = Field(default=None, ge=0.0, le=10.0)
    matriz_pontuacao: MatrizPontuacao | None = None
    feedback: str = Field(..., min_length=1)
    flags: list[FlagCorrecao] = Field(default_factory=list)
    confianca: NivelConfianca

    @field_validator("ra", mode="before")
    @classmethod
    def normaliza_ra(cls, v: str) -> str:
        return _normaliza_ra(v)

    @field_validator("feedback", mode="before")
    @classmethod
    def strip_feedback(cls, v: str) -> str:
        if not isinstance(v, str):
            raise TypeError("feedback deve ser string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("feedback não pode ser vazio ou apenas espaços")
        return stripped


class RespostaBatch(BaseModel):
    """Resposta de um lote processado pelo Clone — estado interno (ADR-002).

    No estado interno da aplicação, ``fichas`` pode ser vazio (decisão da
    Story 1.9 — ver Notas Técnicas no story file). A constraint
    ``min_length=1`` do ADR-002 se aplica à resposta da IA validada pelo
    Wrapper via ``RespostaBatchIA``, não a este modelo de estado.
    """

    fichas: list[FichaCorrecao] = Field(default_factory=list)
    observacoes_gerais: str | None = None


class RespostaBatchIA(BaseModel):
    """Schema de validação da resposta da IA — fronteira IA→app (ADR-002).

    Aplica a constraint ``min_length=1`` conforme ADR-002: a IA deve sempre
    retornar ao menos uma ficha. Use este schema no Wrapper ao parsear a
    resposta do Clone, nunca ``RespostaBatch`` diretamente.
    """

    fichas: list[FichaCorrecao] = Field(..., min_length=1)
    observacoes_gerais: str | None = None


# ---------------------------------------------------------------------------
# Modelos adicionais do pipeline interno
# ---------------------------------------------------------------------------


class Aluno(BaseModel):
    """Aluno cadastrado para correção (linha da planilha)."""

    ra: str = Field(
        ...,
        pattern=r"^\d{11}$",
        description="RA normalizado 11 dígitos (ADR-001)",
    )
    nome: str
    email: str | None = None
    telefone: str | None = None

    @field_validator("ra", mode="before")
    @classmethod
    def normaliza_ra(cls, v: str) -> str:
        return _normaliza_ra(v)


class ArquivoConvertido(BaseModel):
    """Resultado da conversão de um arquivo de aluno para texto."""

    ra: str
    nome_arquivo: str
    texto: str
    metodo_extracao: MetodoExtracao
    flags: list[FlagCorrecao] = Field(default_factory=list)


class ResultadoLote(BaseModel):
    """Resultado de processamento de um lote de fichas."""

    lote_num: int
    fichas: list[FichaCorrecao] = Field(default_factory=list)
    custo_usd: float = Field(default=0.0, ge=0.0)
    status: StatusLote = "pendente"


class EstadoBatch(BaseModel):
    """Estado completo do batch de correções em andamento."""

    disciplina: str
    data_aula: str
    atividade: str
    alunos: list[Aluno] = Field(default_factory=list)
    lotes: list[ResultadoLote] = Field(default_factory=list)
    status_geral: StatusBatch = "configurando"

    @field_validator("data_aula", mode="before")
    @classmethod
    def normaliza_data_aula(cls, v: str) -> str:
        """Aceita ISO (YYYY-MM-DD) e BR (DD/MM/YYYY); normaliza para ISO."""
        if not isinstance(v, str):
            raise TypeError("data_aula deve ser string")
        v = v.strip()
        if _RE_DATA_ISO.match(v):
            return v
        if _RE_DATA_BR.match(v):
            dia, mes, ano = v.split("/")
            return f"{ano}-{mes}-{dia}"
        raise ValueError(f"data_aula '{v}' não está no formato YYYY-MM-DD ou DD/MM/YYYY")


__all__ = [
    "Aluno",
    "ArquivoConvertido",
    "EstadoBatch",
    "FichaCorrecao",
    "FlagCorrecao",
    "MatrizPontuacao",
    "MetodoExtracao",
    "NivelConfianca",
    "RespostaBatch",
    "RespostaBatchIA",
    "ResultadoLote",
    "StatusBatch",
    "StatusLote",
]
