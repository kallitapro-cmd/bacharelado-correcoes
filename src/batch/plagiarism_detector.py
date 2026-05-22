"""Detector de plágio por similaridade textual (Story 2.4).

Componente puro e isolado que recebe uma lista de
:class:`TrabalhoParaComparacao` e retorna pares suspeitos
(:class:`ParPlagio`) com similaridade ``>= threshold``.

Implementa exatamente a especificação do ADR-006
(``docs/decisions/ADR-006-plagio-policy.md``):

- Algoritmo: ``difflib.SequenceMatcher`` (stdlib Python, zero dependências
  externas).
- Threshold default: ``0.70`` (configurável).
- Severidade: ``70% <= sim < 90%`` → ``"amarelo"``;
  ``90% <= sim <= 100%`` → ``"vermelho"``.
- Garantia estrutural ADR-006: o detector **não tem acesso ao campo
  ``nota``** — a dataclass de entrada (:class:`TrabalhoParaComparacao`)
  contém apenas ``aluno_id`` e ``texto``.

Story 2.5 (integração com ``group_detector``) adiciona, de forma
*additive*, o parâmetro opcional ``grupos_conhecidos`` em
:func:`detectar_plagio_no_batch`: quando informado, pares cujos alunos
pertencem ao mesmo :class:`~src.batch.group_detector.GrupoCandidato`
têm sua flag suprimida.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.batch.group_detector import GrupoCandidato


# ---------------------------------------------------------------------------
# Dataclasses públicas
# ---------------------------------------------------------------------------


@dataclass
class TrabalhoParaComparacao:
    """Entrada mínima do detector — SEM campo ``nota`` (AC-06 da Story 2.4).

    A separação estrutural garante que o detector é incapaz de modificar
    notas mesmo por engano — não há acesso ao campo.
    """

    aluno_id: str  # RA como string (ADR-001)
    texto: str  # conteúdo textual já extraído do trabalho


@dataclass
class ParPlagio:
    """Par suspeito de plágio retornado pelo detector."""

    aluno_a: str  # RA do primeiro aluno
    aluno_b: str  # RA do segundo aluno
    similaridade: float  # razão SequenceMatcher entre 0.0 e 1.0
    severidade: Literal["amarelo", "vermelho"]


# ---------------------------------------------------------------------------
# Funções públicas
# ---------------------------------------------------------------------------


_RE_WHITESPACE = re.compile(r"\s+")
_RE_NAO_TEXTUAL = re.compile(r"[^\w\sáéíóúãõâêîôûàèìòùçÁÉÍÓÚÃÕÂÊÎÔÛÀÈÌÒÙÇ]")


def preprocess(texto: str) -> str:
    """Normaliza texto antes da comparação (ADR-006).

    Regras (na ordem):

    1. Converte para lowercase.
    2. Remove caracteres não-textuais (pontuação, símbolos).
    3. Normaliza whitespace (múltiplos espaços/quebras → espaço único).

    **NÃO remove stopwords** — manteria viés contra textos curtos
    (ADR-006, seção "Pré-processamento", regra 4).
    """
    if not texto:
        return ""
    texto = texto.lower()
    texto = _RE_NAO_TEXTUAL.sub(" ", texto)
    texto = _RE_WHITESPACE.sub(" ", texto)
    return texto.strip()


def calcular_similaridade(texto_a: str, texto_b: str) -> float:
    """Retorna razão de similaridade entre 0.0 e 1.0 (ADR-006).

    Usa ``difflib.SequenceMatcher(None, texto_a, texto_b).ratio()``
    exatamente conforme o ADR-006 — sem variações algorítmicas.

    Args:
        texto_a: primeiro texto (idealmente já pré-processado).
        texto_b: segundo texto (idealmente já pré-processado).

    Returns:
        Razão entre 0.0 (textos disjuntos) e 1.0 (idênticos).
    """
    return difflib.SequenceMatcher(None, texto_a, texto_b).ratio()


def _classificar_severidade(sim: float) -> Literal["amarelo", "vermelho"]:
    """Mapeia similaridade → severidade visual (ADR-006).

    - ``0.70 <= sim < 0.90`` → ``"amarelo"``
    - ``0.90 <= sim <= 1.00`` → ``"vermelho"``
    """
    if sim >= 0.90:
        return "vermelho"
    return "amarelo"


def _indice_pares_por_grupo(
    grupos_conhecidos: list[GrupoCandidato] | None,
) -> dict[frozenset[str], GrupoCandidato]:
    """Pré-computa mapa ``{frozenset({ra_a, ra_b}): grupo}``.

    Cada par é representado como ``frozenset({ra_a, ra_b})`` para que a
    ordem dos RAs não importe. O valor é o :class:`GrupoCandidato` que
    causou a supressão — usado para popular ``grupo.pares_suprimidos`` e
    dar visibilidade ao PA do que foi ocultado (Story 2.5).
    """
    indice: dict[frozenset[str], GrupoCandidato] = {}
    if not grupos_conhecidos:
        return indice
    for grupo in grupos_conhecidos:
        membros = list(grupo.membros)
        for i in range(len(membros)):
            for j in range(i + 1, len(membros)):
                indice[frozenset({membros[i], membros[j]})] = grupo
    return indice


def detectar_plagio_no_batch(
    trabalhos: list[TrabalhoParaComparacao],
    threshold: float = 0.70,
    grupos_conhecidos: list[GrupoCandidato] | None = None,
) -> list[ParPlagio]:
    """Compara todos os pares O(n²) e retorna suspeitos (ADR-006).

    Args:
        trabalhos: lista de :class:`TrabalhoParaComparacao`. Para batch típico
            de 120 alunos, são ``120 * 119 / 2 = 7.140`` comparações
            (~25-35s — ADR-006).
        threshold: similaridade mínima para incluir o par no resultado.
            Default ``0.70``. Pares com ``sim == threshold`` SÃO incluídos.
        grupos_conhecidos: lista opcional de :class:`GrupoCandidato`
            (Story 2.5). Quando informada, pares cujos alunos pertencem ao
            mesmo grupo têm suas flags **suprimidas** (não aparecem no
            resultado). Quando ``None``, comportamento idêntico ao da Story
            2.4 original.

    Returns:
        Lista de :class:`ParPlagio` com ``similaridade >= threshold``,
        cada um classificado por severidade.
    """
    # Pré-processa uma vez por trabalho — evita N*(N-1) chamadas a preprocess
    textos_pre = [preprocess(t.texto) for t in trabalhos]
    pares_indexados = _indice_pares_por_grupo(grupos_conhecidos)

    pares_suspeitos: list[ParPlagio] = []
    n = len(trabalhos)
    for i in range(n):
        for j in range(i + 1, n):
            par_chave = frozenset({trabalhos[i].aluno_id, trabalhos[j].aluno_id})
            # Cálculo de similaridade ANTES da supressão — assim podemos
            # popular grupo.pares_suprimidos com a similaridade real (dá ao
            # PA visibilidade do que foi ocultado, conforme dataclass extendida
            # da Story 2.5).
            sim = calcular_similaridade(textos_pre[i], textos_pre[j])

            if sim >= threshold and par_chave in pares_indexados:
                # AC-05 Story 2.5: par no mesmo grupo conhecido — suprime
                # mas registra para visibilidade.
                grupo = pares_indexados[par_chave]
                grupo.pares_suprimidos.append((trabalhos[i].aluno_id, trabalhos[j].aluno_id, sim))
                continue

            if sim >= threshold:
                pares_suspeitos.append(
                    ParPlagio(
                        aluno_a=trabalhos[i].aluno_id,
                        aluno_b=trabalhos[j].aluno_id,
                        similaridade=sim,
                        severidade=_classificar_severidade(sim),
                    )
                )
    return pares_suspeitos
