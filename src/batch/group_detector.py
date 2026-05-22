"""Detector de candidatos a grupo por sobreposição nominal (Story 2.5).

Heurística complementar ao :mod:`src.batch.plagiarism_detector`: identifica
trabalhos potencialmente entregues em grupo a partir de evidência textual
nos próprios trabalhos — sem depender de coluna ``grupo`` declarada na
planilha (essa fica como roadmap futuro do ADR-006).

Mecânica resumida:

1. Para cada trabalho, extrai *menções nominais* a alunos do cadastro
   usando ``difflib.get_close_matches`` (cutoff 0.75 — fuzzy matching
   tolerante a variações de grafia).
2. Quando um token corresponde a **mais de um aluno** do cadastro, o token
   é considerado *ambíguo*: não é incluído nos membros e a ocorrência é
   registrada nas ``evidencias`` (AC-01, regra de ambiguidade).
3. Constrói grafo de menções: aresta ``A → B`` se trabalho de ``A``
   menciona o nome de ``B``.
4. Agrupa componentes conectados. Confiança (AC-03):

   - ``"alta"`` — pelo menos um par do grupo se menciona mutuamente
     (``A → B`` **e** ``B → A``).
   - ``"media"`` — apenas menções unilaterais entre os membros.
   - ``"baixa"`` — grupo contém token ambíguo (AC-01) **ou** tem mais de 4
     membros (AC-02, regra de tamanho) — exige revisão manual do PA.

Conformidade:

- AC-04: NUNCA modifica ``nota`` nem ``flags`` das fichas — retorna
  apenas ``list[GrupoCandidato]`` sem efeitos colaterais.
- AC-06: 100% local, sem I/O externo, sem chamada à API (ADR-004).
- Zero dependências externas — apenas stdlib (``difflib``, ``re``,
  ``dataclasses``, ``typing``).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Dataclasses públicas
# ---------------------------------------------------------------------------


@dataclass
class GrupoCandidato:
    """Conjunto de alunos suspeitos de terem feito o trabalho em grupo.

    Notas técnicas (Story 2.5):

    - ``pares_suprimidos`` é populado pelo
      :func:`~src.batch.plagiarism_detector.detectar_plagio_no_batch`
      quando este grupo causou a supressão de um par flaggável — permite
      ao PA ver na UI (Sprint 3) o que o sistema decidiu ocultar.
    - ``razao_confianca`` é texto legível para o PA — não é parseado pelo
      sistema, é apenas para apresentação.
    - ``status_revisao`` é placeholder para Sprint 3 (revisão do PA).
    """

    membros: list[str]  # lista de RAs (str) — identificador canônico
    evidencias: list[str] = field(default_factory=list)  # trechos do texto
    confianca: Literal["alta", "media", "baixa"] = "media"
    pares_suprimidos: list[tuple[str, str, float]] = field(default_factory=list)
    # (ra_a, ra_b, similaridade) — pares que seriam flag de plágio mas foram
    # suprimidos por este grupo (visibilidade para tabela Sprint 3).
    razao_confianca: str = ""
    # texto legível para o PA: ex. "Ana mencionou Carlos e Carlos mencionou Ana"
    status_revisao: Literal["pendente", "confirmado_pa", "rejeitado_pa"] = "pendente"
    # campo previsto para Sprint 3: PA confirma, rejeita ou deixa pendente.


@dataclass
class AlunoRef:
    """Referência mínima de aluno usada pelo detector — apenas ra+nome.

    Intencionalmente **não** importa :class:`src.models.schemas.Aluno`
    para evitar acoplamento com o schema Pydantic completo (que carrega
    e-mail/telefone) — o detector só precisa do nome para o matching.
    """

    ra: str
    nome: str


# ---------------------------------------------------------------------------
# Parâmetros do matching (constantes documentadas, não números mágicos)
# ---------------------------------------------------------------------------

# Cutoff do fuzzy matching — AC-01. Conforme story, 0.75 tolera variações
# como "Brunu" ↔ "Bruno" sem confundir "Ana" com "Anna" em textos longos.
_FUZZY_CUTOFF = 0.75

# Tamanho mínimo de token (em caracteres) considerado um nome próprio
# candidato — evita falsos positivos com palavras curtas (Risco 2 da story).
_TOKEN_MIN_LEN = 3

# AC-02: grupos com mais de _MAX_MEMBROS_CONFIANCA_PLENA membros são
# automaticamente rebaixados para "baixa" — grupos reais de 5+ integrantes
# em trabalho acadêmico são raros e exigem revisão manual do PA.
_MAX_MEMBROS_CONFIANCA_PLENA = 4

# Regex para identificar tokens com inicial maiúscula — candidatos a nome
# próprio. Aceita acentos PT-BR. Anchorado por word boundary para não
# capturar metade de palavra.
_RE_TOKEN_NOME = re.compile(r"\b[A-ZÁÉÍÓÚÃÕÂÊÎÔÛÀÈÌÒÙÇ][a-záéíóúãõâêîôûàèìòùç]+\b")

# Regex para extrair um trecho-contexto ao redor de um token (evidência).
_CONTEXT_BEFORE = 30
_CONTEXT_AFTER = 30

# Marcador de evidência para casos ambíguos (AC-01).
_EVIDENCIA_AMBIGUO = "Nome ambíguo: {n} alunos com nome similar encontrados"


# ---------------------------------------------------------------------------
# Internals — extração e helpers
# ---------------------------------------------------------------------------


def _primeiro_nome(nome_completo: str) -> str:
    """Extrai o primeiro nome de um ``nome_completo`` (ex.: "Bruno Silva"→"Bruno")."""
    return nome_completo.strip().split()[0] if nome_completo.strip() else ""


def _extrair_tokens_candidatos(texto: str) -> list[str]:
    """Extrai tokens com inicial maiúscula e tamanho >= _TOKEN_MIN_LEN."""
    return [tok for tok in _RE_TOKEN_NOME.findall(texto) if len(tok) >= _TOKEN_MIN_LEN]


def _contexto_ao_redor(texto: str, token: str) -> str:
    """Retorna trecho ao redor da primeira ocorrência de ``token`` em ``texto``."""
    idx = texto.lower().find(token.lower())
    if idx < 0:
        return token
    inicio = max(0, idx - _CONTEXT_BEFORE)
    fim = min(len(texto), idx + len(token) + _CONTEXT_AFTER)
    trecho = texto[inicio:fim].strip()
    return f"...{trecho}..." if (inicio > 0 or fim < len(texto)) else trecho


def _construir_indice_nomes(
    alunos: list[AlunoRef],
) -> tuple[dict[str, list[str]], list[str]]:
    """Indexa cadastro por primeiro-nome (lowercased).

    Returns:
        ``(nome_para_ras, nomes_unicos)`` onde:

        - ``nome_para_ras[nome_lower]`` é a lista de RAs que compartilham
          aquele primeiro nome (≥2 ⇒ homônimos detectáveis).
        - ``nomes_unicos`` é a lista de primeiros nomes únicos para o
          ``get_close_matches`` operar.
    """
    nome_para_ras: dict[str, list[str]] = {}
    for aluno in alunos:
        primeiro = _primeiro_nome(aluno.nome).lower()
        if not primeiro or len(primeiro) < _TOKEN_MIN_LEN:
            continue
        nome_para_ras.setdefault(primeiro, []).append(aluno.ra)
    return nome_para_ras, list(nome_para_ras.keys())


# ---------------------------------------------------------------------------
# Funções públicas
# ---------------------------------------------------------------------------


def extrair_candidatos_grupo(
    texto: str,
    alunos: list[AlunoRef],
    evidencias_ambiguidade: list[str] | None = None,
) -> list[str]:
    """Retorna RAs de alunos mencionados (por nome) dentro do ``texto`` (AC-01).

    Usa ``difflib.get_close_matches`` com ``cutoff=0.75`` para tolerar
    variações de grafia (ex.: "Brunu" → "Bruno"; "Rodrigo" → "Rodrigo
    Ferreira" cujo primeiro nome está no cadastro).

    **Regra de ambiguidade (AC-01):** quando o mesmo primeiro nome
    corresponde a **mais de um aluno** no cadastro (homônimos), o token é
    descartado e a ocorrência é registrada no parâmetro de saída
    ``evidencias_ambiguidade`` (se informado).

    Args:
        texto: trabalho do aluno (ou trecho dele).
        alunos: lista de :class:`AlunoRef` do cadastro.
        evidencias_ambiguidade: lista mutável onde marcadores de
            ambiguidade serão *appendados*. Quando ``None``, ambiguidade é
            silenciosa (mas o token ainda é descartado).

    Returns:
        Lista de RAs (sem duplicados, ordem estável) de alunos mencionados
        com correspondência *não ambígua*.
    """
    if not texto or not alunos:
        return []

    tokens = _extrair_tokens_candidatos(texto)
    if not tokens:
        return []

    nome_para_ras, nomes_unicos = _construir_indice_nomes(alunos)
    if not nome_para_ras:
        return []

    ras_encontrados: list[str] = []
    vistos: set[str] = set()
    ambiguidades_registradas: set[str] = set()  # evita duplicar evidência

    for token in tokens:
        token_lower = token.lower()

        # Match exato preferido sobre fuzzy.
        if token_lower in nome_para_ras:
            ras_candidatos = nome_para_ras[token_lower]
            nome_canonico = token_lower
        else:
            matches = difflib.get_close_matches(
                token_lower, nomes_unicos, n=3, cutoff=_FUZZY_CUTOFF
            )
            if not matches:
                continue
            # Quando o fuzzy retorna múltiplos candidatos COM o mesmo score
            # próximo, consideramos ambíguo. Estratégia: se houver mais de
            # 1 nome distinto com cutoff >= _FUZZY_CUTOFF, é ambíguo.
            if len(matches) > 1:
                # Confirma que são realmente distintos (não apenas variações
                # do mesmo nome) e que cada um aponta para alunos diferentes.
                ras_unicos_dos_matches = {ra for m in matches for ra in nome_para_ras.get(m, [])}
                if len(ras_unicos_dos_matches) > 1:
                    chave = token_lower
                    if chave not in ambiguidades_registradas:
                        ambiguidades_registradas.add(chave)
                        if evidencias_ambiguidade is not None:
                            evidencias_ambiguidade.append(
                                _EVIDENCIA_AMBIGUO.format(n=len(ras_unicos_dos_matches))
                            )
                    continue
            ras_candidatos = nome_para_ras[matches[0]]
            nome_canonico = matches[0]

        # Mesmo após match exato/fuzzy único, se o NOME canônico tem >1 RA
        # (homônimos no cadastro), é ambíguo.
        if len(ras_candidatos) > 1:
            chave = nome_canonico
            if chave not in ambiguidades_registradas:
                ambiguidades_registradas.add(chave)
                if evidencias_ambiguidade is not None:
                    evidencias_ambiguidade.append(_EVIDENCIA_AMBIGUO.format(n=len(ras_candidatos)))
            continue

        ra = ras_candidatos[0]
        if ra not in vistos:
            ras_encontrados.append(ra)
            vistos.add(ra)
    return ras_encontrados


def _componentes_conectados(
    arestas: Iterable[tuple[str, str]],
    nos: Iterable[str],
) -> list[set[str]]:
    """Encontra componentes conectados num grafo não-direcionado (DFS iterativo)."""
    adj: dict[str, set[str]] = {n: set() for n in nos}
    for origem, destino in arestas:
        adj.setdefault(origem, set()).add(destino)
        adj.setdefault(destino, set()).add(origem)

    visitados: set[str] = set()
    componentes: list[set[str]] = []
    for no in adj:
        if no in visitados:
            continue
        pilha = [no]
        comp: set[str] = set()
        while pilha:
            atual = pilha.pop()
            if atual in visitados:
                continue
            visitados.add(atual)
            comp.add(atual)
            pilha.extend(adj[atual] - visitados)
        if len(comp) >= 2:  # grupos singleton não são candidatos
            componentes.append(comp)
    return componentes


def _ra_para_nome(ra: str, alunos: list[AlunoRef]) -> str:
    """Helper: retorna o primeiro nome do aluno cujo RA == ``ra`` (ou ``ra``)."""
    for aluno in alunos:
        if aluno.ra == ra:
            return _primeiro_nome(aluno.nome)
    return ra


def _construir_razao_confianca(
    membros: list[str],
    mencoes: dict[str, set[str]],
    alunos: list[AlunoRef],
    confianca: Literal["alta", "media", "baixa"],
    grupo_grande: bool,
    tem_ambiguidade: bool,
) -> str:
    """Gera texto legível para o PA descrevendo a confiança (AC-08, TC-08).

    Exemplos:
        - "Ana mencionou Carlos e Carlos mencionou Ana (menção mútua)."
        - "Ana mencionou Carlos, mas Carlos não mencionou Ana (unilateral)."
        - "Grupo com 5 membros — rebaixado para 'baixa' (regra de tamanho)."
        - "Token ambíguo encontrado — confiança rebaixada para 'baixa'."
    """
    nomes_por_ra = {ra: _ra_para_nome(ra, alunos) or ra for ra in membros}

    if grupo_grande:
        return (
            f"Grupo com {len(membros)} membros — rebaixado para 'baixa' "
            "(regra de tamanho: mais de 4 integrantes exige revisão manual)."
        )
    if tem_ambiguidade:
        return (
            "Token ambíguo encontrado (nome corresponde a múltiplos alunos no "
            "cadastro) — confiança rebaixada para 'baixa' para revisão manual."
        )

    if confianca == "alta":
        # Encontra um par mutual para exemplificar
        for ra_a in membros:
            for ra_b in mencoes.get(ra_a, set()):
                if ra_b in membros and ra_a in mencoes.get(ra_b, set()):
                    nome_a = nomes_por_ra[ra_a]
                    nome_b = nomes_por_ra[ra_b]
                    return (
                        f"{nome_a} mencionou {nome_b} e {nome_b} mencionou "
                        f"{nome_a} (menção mútua — confiança alta)."
                    )
        return "Menção mútua detectada entre membros — confiança alta."

    # confianca == "media"
    for ra_a in membros:
        for ra_b in mencoes.get(ra_a, set()):
            if ra_b in membros:
                nome_a = nomes_por_ra[ra_a]
                nome_b = nomes_por_ra[ra_b]
                return (
                    f"{nome_a} mencionou {nome_b}, mas não houve reciprocidade "
                    "(unilateral — confiança média)."
                )
    return "Menção unilateral entre membros — confiança média."


def detectar_grupos_candidatos(
    trabalhos: list[Any],  # objetos com .aluno_id e .texto (duck-typed)
    alunos: list[AlunoRef],
) -> list[GrupoCandidato]:
    """Identifica candidatos a trabalhos em grupo (AC-02, AC-03).

    Cada elemento de ``trabalhos`` deve ter ao menos os atributos
    ``aluno_id`` (RA) e ``texto`` — compatível com
    :class:`~src.batch.plagiarism_detector.TrabalhoParaComparacao` e com
    qualquer dataclass/namespace equivalente.

    Args:
        trabalhos: lista de trabalhos com ``aluno_id`` e ``texto``.
        alunos: cadastro completo (:class:`AlunoRef`) para resolver menções.

    Returns:
        Lista de :class:`GrupoCandidato`. Confiança segue AC-03 + regras
        extras AC-01 (ambiguidade → baixa) e AC-02 (tamanho > 4 → baixa).

    Garantia (AC-04): NÃO modifica nenhum atributo dos ``trabalhos`` nem
    dos ``alunos`` recebidos.
    """
    if not trabalhos or not alunos:
        return []

    # Etapa 1 — para cada trabalho, extrai RAs mencionados e ambiguidades.
    mencoes_por_ra: dict[str, set[str]] = {}  # ra → ras mencionados (sem ambíguos)
    evidencias_por_ra: dict[str, list[str]] = {}
    ambiguidades_por_ra: dict[str, list[str]] = {}

    for trab in trabalhos:
        ra_origem = getattr(trab, "aluno_id", None)
        texto = getattr(trab, "texto", "")
        if not ra_origem or not texto:
            continue
        ambs: list[str] = []
        ras_mencionados = extrair_candidatos_grupo(texto, alunos, ambs)
        # Auto-menção (o próprio aluno no próprio texto) não conta.
        ras_mencionados = [ra for ra in ras_mencionados if ra != ra_origem]
        if not ras_mencionados and not ambs:
            continue
        mencoes_por_ra[ra_origem] = set(ras_mencionados)
        evidencias_por_ra[ra_origem] = [
            _contexto_ao_redor(texto, _ra_para_nome(ra, alunos)) for ra in ras_mencionados
        ]
        if ambs:
            ambiguidades_por_ra[ra_origem] = ambs

    if not mencoes_por_ra and not ambiguidades_por_ra:
        return []

    # Etapa 2 — construir arestas (origem, destino) apenas com menções claras.
    arestas: list[tuple[str, str]] = []
    nos: set[str] = set(mencoes_por_ra.keys())
    for origem, destinos in mencoes_por_ra.items():
        for dest in destinos:
            arestas.append((origem, dest))
            nos.add(dest)

    # Etapa 3 — componentes conectados → grupos candidatos.
    componentes = _componentes_conectados(arestas, nos)

    grupos: list[GrupoCandidato] = []
    for comp in componentes:
        membros = sorted(comp)

        # AC-03: alta se houver pelo menos um par mutual.
        mutual = False
        for ra_a in comp:
            destinos_a = mencoes_por_ra.get(ra_a, set())
            for ra_b in destinos_a:
                if ra_b in comp and ra_a in mencoes_por_ra.get(ra_b, set()):
                    mutual = True
                    break
            if mutual:
                break

        # AC-01: presença de qualquer evidência ambígua em qualquer membro
        # do grupo rebaixa o grupo inteiro para "baixa".
        tem_ambiguidade = any(ra in ambiguidades_por_ra for ra in comp)

        # AC-02: grupo > 4 membros → rebaixa para "baixa".
        grupo_grande = len(membros) > _MAX_MEMBROS_CONFIANCA_PLENA

        if grupo_grande or tem_ambiguidade:
            confianca: Literal["alta", "media", "baixa"] = "baixa"
        elif mutual:
            confianca = "alta"
        else:
            confianca = "media"

        # Evidências agregadas (textuais) + ambiguidades.
        evidencias_agg: list[str] = []
        for ra in membros:
            evidencias_agg.extend(evidencias_por_ra.get(ra, []))
            evidencias_agg.extend(ambiguidades_por_ra.get(ra, []))

        razao = _construir_razao_confianca(
            membros=membros,
            mencoes=mencoes_por_ra,
            alunos=alunos,
            confianca=confianca,
            grupo_grande=grupo_grande,
            tem_ambiguidade=tem_ambiguidade,
        )

        grupos.append(
            GrupoCandidato(
                membros=membros,
                evidencias=evidencias_agg,
                confianca=confianca,
                razao_confianca=razao,
            )
        )
    return grupos
