"""Testes unitários de plagiarism_detector.py — Story 2.4.

Todos os testes são puros — sem mocks, sem I/O externo, sem chamada à IA
(AC-09). Instanciam :class:`TrabalhoParaComparacao` diretamente com strings
literais e validam o comportamento determinístico do algoritmo
``difflib.SequenceMatcher``.

Cobertura mínima exigida pela Story 2.4 — 8 testes mapeados aos ACs:

| # | Teste                                                          | AC          |
|---|----------------------------------------------------------------|-------------|
| 1 | similaridade 1.0 para textos idênticos                         | AC-01       |
| 2 | similaridade ~0.0 para textos completamente distintos          | AC-01       |
| 3 | par na fronteira (sim == threshold) é incluído no resultado    | AC-07, AC-03|
| 4 | severidade "amarelo" para similaridade 70–89%                  | AC-05       |
| 5 | severidade "vermelho" para similaridade ≥ 90%                  | AC-05       |
| 6 | preprocess normaliza whitespace múltiplo e maiúsculas          | AC-02       |
| 7 | performance: N=120 textos sintéticos de ~5.000 chars ≤ 60s     | AC-08       |
| 8 | TrabalhoParaComparacao não possui atributo ``nota``            | AC-06       |

Referências: ADR-006 (algoritmo, threshold, severidade), ADR-004 (processamento
100% local — nenhum texto sai do sistema durante os testes).
"""

from __future__ import annotations

import random
import string
import time

import pytest

from src.batch.plagiarism_detector import (
    ParPlagio,
    TrabalhoParaComparacao,
    calcular_similaridade,
    detectar_plagio_no_batch,
    preprocess,
)

# ---------------------------------------------------------------------------
# Helpers — geração de textos sintéticos para o teste de performance (TC-07)
# ---------------------------------------------------------------------------


def _gerar_texto(seed: int, tamanho: int = 5000) -> str:
    """Gera texto aleatório determinístico para o teste de performance (AC-08).

    Usa apenas letras minúsculas + espaço para que ``preprocess`` seja
    essencialmente identidade — assim o teste mede o custo real do loop O(n²)
    sobre ``SequenceMatcher.ratio()``, não o overhead de regex.

    Seeds distintos produzem textos quase disjuntos, fazendo a similaridade
    cair muito abaixo do threshold default — o resultado é uma lista vazia,
    o que isola o custo do *cálculo* (sem custo extra de criar ``ParPlagio``).
    """
    rng = random.Random(seed)
    return "".join(rng.choices(string.ascii_lowercase + " ", k=tamanho))


# ---------------------------------------------------------------------------
# TC-01 — calcular_similaridade: textos idênticos retornam 1.0 (AC-01)
# ---------------------------------------------------------------------------


def test_tc01_similaridade_textos_identicos_retorna_um():
    texto = "A teoria geral dos sistemas tem origem nos trabalhos de Bertalanffy."
    assert calcular_similaridade(texto, texto) == 1.0


# ---------------------------------------------------------------------------
# TC-02 — calcular_similaridade: textos sem sobreposição ~ 0.0 (AC-01)
# ---------------------------------------------------------------------------


def test_tc02_similaridade_textos_completamente_distintos_proxima_zero():
    # Conjuntos de caracteres disjuntos — sem qualquer letra em comum
    texto_a = "aaaaaaaaaa"
    texto_b = "zzzzzzzzzz"
    sim = calcular_similaridade(texto_a, texto_b)
    # SequenceMatcher.ratio() = 0.0 quando não há matching block algum
    assert sim == 0.0


# ---------------------------------------------------------------------------
# TC-03 — par na fronteira (sim == threshold) é incluído (AC-07, AC-03)
# ---------------------------------------------------------------------------


def test_tc03_par_na_fronteira_do_threshold_eh_incluido():
    """Quando ``similaridade == threshold``, o par DEVE entrar no resultado.

    A comparação no detector é ``sim >= threshold`` (não ``>``).
    Construímos um par determinístico, lemos a similaridade exata calculada,
    e usamos essa similaridade COMO threshold. O par deve aparecer.
    """
    texto_a = "Análise sistêmica das organizações educacionais brasileiras."
    texto_b = "Análise sistêmica das organizações esportivas brasileiras."

    sim_exata = calcular_similaridade(preprocess(texto_a), preprocess(texto_b))

    # Sanity: as duas frases devem ser parecidas o suficiente para o teste
    # fazer sentido (>0.5) mas não idênticas (<1.0). Se o assertion abaixo
    # quebrar, a fixture textual deve ser revisada.
    assert 0.5 < sim_exata < 1.0

    trabalhos = [
        TrabalhoParaComparacao(aluno_id="20260000001", texto=texto_a),
        TrabalhoParaComparacao(aluno_id="20260000002", texto=texto_b),
    ]
    resultado = detectar_plagio_no_batch(trabalhos, threshold=sim_exata)

    assert len(resultado) == 1, "Par com sim == threshold deve estar no resultado"
    par = resultado[0]
    assert par.aluno_a == "20260000001"
    assert par.aluno_b == "20260000002"
    assert par.similaridade == pytest.approx(sim_exata)


# ---------------------------------------------------------------------------
# TC-04 — severidade "amarelo" para similaridade na faixa 70–89% (AC-05)
# ---------------------------------------------------------------------------


def test_tc04_severidade_amarelo_para_faixa_70_a_89():
    """Constrói um par cuja similaridade cai claramente entre 0.70 e 0.90.

    Fixture calibrada empiricamente: similaridade observada ≈ 0.76, dentro da
    faixa amarela. Edições trocam adjetivos e termos finais, mantendo a
    estrutura comum.
    """
    base = (
        "A linguagem Python permite escrever código legível, conciso e "
        "expressivo, sendo amplamente adotada em ciência de dados, "
        "automação e desenvolvimento web."
    )
    # Edição moderada — preserva esqueleto, troca adjetivos e palavras finais
    variacao = (
        "A linguagem Python permite escrever código simples, claro e "
        "direto, sendo amplamente empregada em análise estatística, "
        "automação e desenvolvimento backend."
    )

    sim_exata = calcular_similaridade(preprocess(base), preprocess(variacao))
    # Pré-condição da fixture: deve cair na faixa amarela
    assert 0.70 <= sim_exata < 0.90, f"Fixture inválida: sim={sim_exata}"

    trabalhos = [
        TrabalhoParaComparacao(aluno_id="A", texto=base),
        TrabalhoParaComparacao(aluno_id="B", texto=variacao),
    ]
    resultado = detectar_plagio_no_batch(trabalhos, threshold=0.70)

    assert len(resultado) == 1
    assert resultado[0].severidade == "amarelo"


# ---------------------------------------------------------------------------
# TC-05 — severidade "vermelho" para similaridade >= 90% (AC-05)
# ---------------------------------------------------------------------------


def test_tc05_severidade_vermelho_para_similaridade_acima_90():
    """Par com edição mínima deve gerar severidade vermelha (sim >= 0.90)."""
    base = (
        "O método científico envolve observação, formulação de hipóteses, "
        "experimentação controlada, análise dos resultados e conclusões "
        "passíveis de revisão por pares na comunidade acadêmica."
    )
    # Mudança mínima: apenas uma palavra
    quase_identico = (
        "O método científico envolve observação, formulação de hipóteses, "
        "experimentação controlada, análise dos resultados e conclusões "
        "passíveis de revisão por colegas na comunidade acadêmica."
    )

    sim_exata = calcular_similaridade(preprocess(base), preprocess(quase_identico))
    assert sim_exata >= 0.90, f"Fixture inválida para vermelho: sim={sim_exata}"

    trabalhos = [
        TrabalhoParaComparacao(aluno_id="A", texto=base),
        TrabalhoParaComparacao(aluno_id="B", texto=quase_identico),
    ]
    resultado = detectar_plagio_no_batch(trabalhos, threshold=0.70)

    assert len(resultado) == 1
    assert resultado[0].severidade == "vermelho"


# ---------------------------------------------------------------------------
# TC-06 — preprocess normaliza whitespace e maiúsculas antes da comparação
# (AC-02)
# ---------------------------------------------------------------------------


def test_tc06_preprocess_normaliza_whitespace_e_maiusculas():
    """``preprocess`` deve normalizar ws múltiplo + lowercase ANTES da
    comparação, de modo que duas variantes apenas em formatação retornem
    similaridade 1.0.
    """
    texto_a = "Olá    Mundo\n\tTexto exemplo"
    texto_b = "olá mundo texto exemplo"

    pre_a = preprocess(texto_a)
    pre_b = preprocess(texto_b)

    # Whitespace múltiplo → único; maiúsculas → minúsculas
    assert pre_a == pre_b == "olá mundo texto exemplo"

    # E a similaridade do par já preprocessado é exatamente 1.0
    assert calcular_similaridade(pre_a, pre_b) == 1.0


# ---------------------------------------------------------------------------
# TC-07 — performance: N=120 textos sintéticos completam ≤ 60s (AC-08)
# ---------------------------------------------------------------------------
# Sobrescreve o ``timeout = 20`` global do pyproject.toml — este teste tem
# orçamento próprio de 60s + margem.


@pytest.mark.timeout(120)
def test_tc07_performance_batch_120_textos_sinteticos_em_60s():
    """Batch de 120 trabalhos com ~5.000 chars: 7.140 comparações em ≤ 60s.

    Conforme ADR-006, o tempo esperado é ~25-35s em hardware de desenvolvimento.
    O limite de 60s no AC-08 dá margem de 2x para ambientes de CI mais lentos.
    """
    trabalhos = [
        TrabalhoParaComparacao(aluno_id=f"RA{i:05d}", texto=_gerar_texto(seed=i))
        for i in range(120)
    ]

    inicio = time.perf_counter()
    resultado = detectar_plagio_no_batch(trabalhos, threshold=0.70)
    elapsed = time.perf_counter() - inicio

    assert elapsed <= 60.0, f"Performance fora do AC-08: {elapsed:.1f}s > 60s para 120 trabalhos"
    # Textos com seeds distintos produzem similaridade << 0.70 — esperamos
    # lista vazia. Não asseguramos rigorosamente isso para evitar fragilidade
    # estatística, mas a contagem deve ser pequena.
    assert isinstance(resultado, list)
    assert len(resultado) <= 5, (
        f"Inesperado: {len(resultado)} pares 'plágio' em textos aleatórios — "
        "fixture aleatória pode ter colidido por azar"
    )


# ---------------------------------------------------------------------------
# TC-08 — separação estrutural AC-06: TrabalhoParaComparacao SEM nota
# ---------------------------------------------------------------------------


def test_tc08_trabalho_para_comparacao_nao_possui_atributo_nota():
    """Garantia do ADR-006: o detector não tem acesso ao campo ``nota``.

    Esta separação estrutural impede, por design, que o módulo modifique notas
    automaticamente — o atributo não existe na dataclass de entrada.
    """
    trabalho = TrabalhoParaComparacao(aluno_id="20260000099", texto="Texto.")

    # Verificação primária — exigida pela tabela de testes da Story 2.4
    assert hasattr(trabalho, "nota") is False

    # Verificação complementar — proibições afins
    proibidos = {"nota", "nota_a1", "feedback", "grade", "score"}
    presentes = {campo for campo in proibidos if hasattr(trabalho, campo)}
    assert presentes == set(), f"Campos proibidos em TrabalhoParaComparacao: {presentes}"


# ---------------------------------------------------------------------------
# Testes complementares (não obrigatórios pela Story, mas blindam AC-03/AC-10)
# ---------------------------------------------------------------------------


def test_tc09_ambos_alunos_do_par_no_resultado_sem_inverter_ordem():
    """AC-03 / ADR-006: ambos os alunos do par são incluídos em ParPlagio.

    A ordem segue a iteração externa do loop O(n²): ``aluno_a`` é o índice
    menor (i), ``aluno_b`` é o maior (j > i).
    """
    trabalhos = [
        TrabalhoParaComparacao(aluno_id="RA1", texto="Texto compartilhado entre dois alunos."),
        TrabalhoParaComparacao(aluno_id="RA2", texto="Texto compartilhado entre dois alunos."),
    ]
    resultado = detectar_plagio_no_batch(trabalhos, threshold=0.70)

    assert len(resultado) == 1
    par = resultado[0]
    assert isinstance(par, ParPlagio)
    assert par.aluno_a == "RA1"  # índice externo (i=0)
    assert par.aluno_b == "RA2"  # índice interno (j=1)
    assert par.similaridade == 1.0
    assert par.severidade == "vermelho"


def test_tc10_batch_vazio_retorna_lista_vazia():
    """AC-03 (caso degenerado): batch sem trabalhos não levanta exceção."""
    assert detectar_plagio_no_batch([], threshold=0.70) == []


def test_tc11_batch_unico_trabalho_retorna_lista_vazia():
    """AC-03 (caso degenerado): com apenas 1 trabalho não há par possível."""
    trabalhos = [TrabalhoParaComparacao(aluno_id="RA1", texto="único")]
    assert detectar_plagio_no_batch(trabalhos, threshold=0.70) == []


def test_tc12_pares_abaixo_do_threshold_nao_aparecem():
    """AC-03: o filtro ``sim >= threshold`` é estritamente respeitado."""
    trabalhos = [
        TrabalhoParaComparacao(aluno_id="A", texto="aaaaaaaaaa"),
        TrabalhoParaComparacao(aluno_id="B", texto="zzzzzzzzzz"),
    ]
    resultado = detectar_plagio_no_batch(trabalhos, threshold=0.70)
    assert resultado == []
