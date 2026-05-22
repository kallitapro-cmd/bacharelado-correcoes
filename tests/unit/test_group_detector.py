"""Testes unitários do ``group_detector`` (Story 2.5).

Cobre TC-01 a TC-08 (AC-01 a AC-07 + regras de ambiguidade e tamanho)
sem mocks: o detector é heurística puramente local
(``difflib`` + regex). A integração com ``plagiarism_detector`` é
exercitada por TC-05.
"""

from __future__ import annotations

from src.batch.group_detector import (
    AlunoRef,
    GrupoCandidato,
    detectar_grupos_candidatos,
    extrair_candidatos_grupo,
)
from src.batch.plagiarism_detector import (
    TrabalhoParaComparacao,
    detectar_plagio_no_batch,
)

# ---------------------------------------------------------------------------
# AlunoRef fixtures — minimal, sem dependência do Pydantic Aluno
# ---------------------------------------------------------------------------

ALUNO_BRUNO = AlunoRef(ra="001", nome="Bruno Silva")
ALUNO_ANA = AlunoRef(ra="A01", nome="Ana Souza")
ALUNO_CARLOS = AlunoRef(ra="C01", nome="Carlos Pereira")


# ---------------------------------------------------------------------------
# TC-01 — AC-01: extrair_candidatos_grupo encontra menção nominal exata
# ---------------------------------------------------------------------------


def test_tc01_extrair_candidatos_encontra_aluno_mencionado_por_nome() -> None:
    """Texto "eu e Bruno fizemos juntos" deve mapear para o RA do Bruno."""
    texto = "Este trabalho foi feito por mim. Eu e Bruno fizemos juntos a parte 2."
    resultado = extrair_candidatos_grupo(texto, [ALUNO_BRUNO])
    assert "001" in resultado


# ---------------------------------------------------------------------------
# TC-02 — AC-01: tolerância a variação de grafia via fuzzy matching
# ---------------------------------------------------------------------------


def test_tc02_extrair_candidatos_tolera_variacao_grafia() -> None:
    """ "Brunu" (typo) deve ser identificado como menção ao "Bruno" do cadastro."""
    texto = "Eu fiz a maior parte do trabalho mas Brunu me ajudou com a introdução."
    resultado = extrair_candidatos_grupo(texto, [ALUNO_BRUNO])
    assert "001" in resultado, (
        f"Esperava '001' (Bruno) via fuzzy match de 'Brunu', mas obtive {resultado}"
    )


# ---------------------------------------------------------------------------
# TC-03 — AC-02 + AC-03: confiança "alta" para menção mútua
# ---------------------------------------------------------------------------


def test_tc03_detectar_grupos_confianca_alta_para_mencao_mutua() -> None:
    """Ana menciona Carlos e Carlos menciona Ana → confianca='alta'."""
    trabalho_ana = TrabalhoParaComparacao(
        aluno_id="A01",
        texto="Fizemos este trabalho. Carlos contribuiu bastante na discussão final.",
    )
    trabalho_carlos = TrabalhoParaComparacao(
        aluno_id="C01",
        texto="Trabalho compartilhado com Ana, que fez a fundamentação teórica.",
    )

    resultado = detectar_grupos_candidatos(
        [trabalho_ana, trabalho_carlos],
        [ALUNO_ANA, ALUNO_CARLOS],
    )

    assert len(resultado) >= 1, "Esperava ao menos 1 grupo candidato"
    grupo = resultado[0]
    assert isinstance(grupo, GrupoCandidato)
    assert grupo.confianca == "alta", (
        f"Esperava confianca='alta' (menção mútua); obtive '{grupo.confianca}'"
    )
    assert "A01" in grupo.membros and "C01" in grupo.membros, (
        f"Esperava A01 e C01 nos membros; obtive {grupo.membros}"
    )


# ---------------------------------------------------------------------------
# TC-04 — AC-02 + AC-03: confiança "media" para menção unilateral
# ---------------------------------------------------------------------------


def test_tc04_detectar_grupos_confianca_media_para_mencao_unilateral() -> None:
    """Ana menciona Carlos, Carlos NÃO menciona Ana → confianca='media'."""
    trabalho_ana = TrabalhoParaComparacao(
        aluno_id="A01",
        texto="Carlos me ajudou bastante neste trabalho, agradeço a colaboração.",
    )
    trabalho_carlos = TrabalhoParaComparacao(
        aluno_id="C01",
        texto="Trabalho individual sobre fenômenos termodinâmicos e suas aplicações.",
    )

    resultado = detectar_grupos_candidatos(
        [trabalho_ana, trabalho_carlos],
        [ALUNO_ANA, ALUNO_CARLOS],
    )

    assert len(resultado) >= 1, "Esperava ao menos 1 grupo candidato"
    grupo = resultado[0]
    assert grupo.confianca == "media", (
        f"Esperava confianca='media' (menção unilateral); obtive '{grupo.confianca}'"
    )


# ---------------------------------------------------------------------------
# TC-05 — AC-05: detectar_plagio_no_batch suprime par do mesmo grupo
# ---------------------------------------------------------------------------


def test_tc05_plagio_suprime_par_no_mesmo_grupo_candidato() -> None:
    """Dois trabalhos com sim>=0.70 marcados como mesmo grupo → par NÃO aparece."""
    texto_compartilhado = (
        "A termodinâmica estuda as transformações de energia em sistemas físicos. "
        "Os princípios fundamentais incluem a conservação de energia, a entropia "
        "como medida de desordem e a impossibilidade do moto perpétuo de segunda "
        "espécie. Aplicações práticas vão desde motores térmicos até refrigeração."
    )
    trabalho_ana = TrabalhoParaComparacao(aluno_id="A01", texto=texto_compartilhado)
    trabalho_carlos = TrabalhoParaComparacao(aluno_id="C01", texto=texto_compartilhado)

    # Sanidade: sem grupos_conhecidos, o par DEVE aparecer (sim=1.0)
    pares_sem_grupo = detectar_plagio_no_batch([trabalho_ana, trabalho_carlos], threshold=0.70)
    assert len(pares_sem_grupo) == 1, (
        f"Pré-condição falhou: esperava 1 par sem grupo, obtive {len(pares_sem_grupo)}"
    )

    # Com grupo conhecido contendo A01 e C01, o par deve ser SUPRIMIDO
    grupo = GrupoCandidato(
        membros=["A01", "C01"],
        evidencias=["evidência fictícia para teste"],
        confianca="alta",
    )
    pares_com_grupo = detectar_plagio_no_batch(
        [trabalho_ana, trabalho_carlos],
        threshold=0.70,
        grupos_conhecidos=[grupo],
    )
    assert len(pares_com_grupo) == 0, (
        f"Esperava 0 pares (par suprimido pelo grupo); obtive "
        f"{[(p.aluno_a, p.aluno_b) for p in pares_com_grupo]}"
    )
    # O grupo deve registrar o par suprimido para visibilidade do PA
    assert len(grupo.pares_suprimidos) == 1, (
        "Esperava grupo.pares_suprimidos populado com o par suprimido"
    )
    ra_a, ra_b, sim = grupo.pares_suprimidos[0]
    assert {ra_a, ra_b} == {"A01", "C01"}
    assert sim >= 0.70


# ---------------------------------------------------------------------------
# TC-06 — AC-01 (regra de ambiguidade): nome ambíguo descarta e registra
# ---------------------------------------------------------------------------


def test_tc06_extrair_candidatos_registra_ambiguidade() -> None:
    """Quando ``get_close_matches`` retorna múltiplos candidatos distintos,
    o token deve ser descartado e a ambiguidade registrada."""
    aluno_joao1 = AlunoRef(ra="J01", nome="João Silva")
    aluno_joao2 = AlunoRef(ra="J02", nome="João Costa")
    texto = "Sobre o desenvolvimento do projeto, João me ajudou bastante."

    evidencias: list[str] = []
    resultado = extrair_candidatos_grupo(
        texto, [aluno_joao1, aluno_joao2], evidencias_ambiguidade=evidencias
    )

    # Nenhum dos dois Joãos deve aparecer (ambíguo)
    assert "J01" not in resultado, f"João ambíguo não pode ser resolvido: {resultado}"
    assert "J02" not in resultado, f"João ambíguo não pode ser resolvido: {resultado}"
    # Evidência de ambiguidade registrada com a contagem
    assert len(evidencias) == 1
    assert "Nome ambíguo" in evidencias[0]
    assert "2 alunos" in evidencias[0]


# ---------------------------------------------------------------------------
# TC-07 — AC-02 (regra de tamanho): grupo > 4 membros → "baixa"
# ---------------------------------------------------------------------------


def test_tc07_grupo_grande_rebaixa_para_baixa() -> None:
    """5 alunos onde cada um menciona os outros 4 → 'baixa' (regra de tamanho)."""
    nomes = ["Pedro", "Renata", "Sofia", "Tiago", "Ursula"]
    alunos = [AlunoRef(ra=f"R{i:02d}", nome=nomes[i]) for i in range(5)]

    trabalhos = []
    for i, aluno in enumerate(alunos):
        outros = [a.nome for j, a in enumerate(alunos) if j != i]
        texto = (
            f"Este trabalho foi feito em conjunto com {', '.join(outros[:-1])} "
            f"e {outros[-1]}. Discutimos amplamente todos os pontos."
        )
        trabalhos.append(TrabalhoParaComparacao(aluno_id=aluno.ra, texto=texto))

    resultado = detectar_grupos_candidatos(trabalhos, alunos)

    assert len(resultado) >= 1, "Esperava ao menos 1 grupo candidato"
    grupo_grande = max(resultado, key=lambda g: len(g.membros))
    assert len(grupo_grande.membros) == 5, (
        f"Esperava grupo com 5 membros; obtive {len(grupo_grande.membros)}"
    )
    assert grupo_grande.confianca == "baixa", (
        f"AC-02 violado: grupo de 5 membros deveria ser 'baixa', obtive '{grupo_grande.confianca}'"
    )
    # Razão deve mencionar a regra de tamanho
    assert (
        "tamanho" in grupo_grande.razao_confianca.lower()
        or "5 membros" in grupo_grande.razao_confianca
    )


# ---------------------------------------------------------------------------
# TC-08 — razao_confianca populada com texto legível
# ---------------------------------------------------------------------------


def test_tc08_grupo_candidato_popula_razao_confianca() -> None:
    """Após detecção mútua, ``razao_confianca`` deve conter nomes legíveis."""
    trabalho_ana = TrabalhoParaComparacao(
        aluno_id="A01",
        texto="Trabalho com Carlos — discutimos juntos a metodologia.",
    )
    trabalho_carlos = TrabalhoParaComparacao(
        aluno_id="C01",
        texto="Ana foi minha parceira neste trabalho, dividimos as tarefas.",
    )

    resultado = detectar_grupos_candidatos(
        [trabalho_ana, trabalho_carlos], [ALUNO_ANA, ALUNO_CARLOS]
    )

    assert len(resultado) >= 1
    grupo = resultado[0]
    assert grupo.razao_confianca != "", "razao_confianca não pode estar vazia"
    assert "Ana" in grupo.razao_confianca or "Carlos" in grupo.razao_confianca, (
        f"razao_confianca deveria mencionar Ana ou Carlos; obtive: '{grupo.razao_confianca}'"
    )


# ---------------------------------------------------------------------------
# TC-EXTRA-A — AC-04: detector NÃO modifica fichas/atributos de entrada
# ---------------------------------------------------------------------------


def test_extra_a_detector_nao_modifica_entradas() -> None:
    """AC-04 — chamada do detector não deve alterar nada nos objetos passados."""
    trabalho_ana = TrabalhoParaComparacao(
        aluno_id="A01",
        texto="Trabalho com Carlos.",
    )
    trabalho_carlos = TrabalhoParaComparacao(
        aluno_id="C01",
        texto="Trabalho com Ana.",
    )
    alunos = [ALUNO_ANA, ALUNO_CARLOS]

    antes = {
        "trab_ana_id": trabalho_ana.aluno_id,
        "trab_ana_texto": trabalho_ana.texto,
        "trab_carlos_id": trabalho_carlos.aluno_id,
        "trab_carlos_texto": trabalho_carlos.texto,
        "ana_ra": ALUNO_ANA.ra,
        "ana_nome": ALUNO_ANA.nome,
        "carlos_ra": ALUNO_CARLOS.ra,
        "carlos_nome": ALUNO_CARLOS.nome,
    }

    _ = detectar_grupos_candidatos([trabalho_ana, trabalho_carlos], alunos)

    depois = {
        "trab_ana_id": trabalho_ana.aluno_id,
        "trab_ana_texto": trabalho_ana.texto,
        "trab_carlos_id": trabalho_carlos.aluno_id,
        "trab_carlos_texto": trabalho_carlos.texto,
        "ana_ra": ALUNO_ANA.ra,
        "ana_nome": ALUNO_ANA.nome,
        "carlos_ra": ALUNO_CARLOS.ra,
        "carlos_nome": ALUNO_CARLOS.nome,
    }

    assert antes == depois, "AC-04 violado: detector modificou atributos de trabalhos/alunos"
    # Garantia adicional: nem 'flags' nem 'nota' foram adicionados ao trabalho
    assert not hasattr(trabalho_ana, "flags")
    assert not hasattr(trabalho_ana, "nota")


# ---------------------------------------------------------------------------
# TC-EXTRA-B — Robustez: inputs vazios
# ---------------------------------------------------------------------------


def test_extra_b_inputs_vazios_retornam_lista_vazia() -> None:
    """Robustez: texto vazio, lista de alunos vazia ou sem trabalhos."""
    assert extrair_candidatos_grupo("", [ALUNO_BRUNO]) == []
    assert extrair_candidatos_grupo("texto qualquer", []) == []
    assert detectar_grupos_candidatos([], [ALUNO_BRUNO]) == []
    assert detectar_grupos_candidatos([TrabalhoParaComparacao(aluno_id="X", texto="abc")], []) == []


# ---------------------------------------------------------------------------
# TC-EXTRA-C — Backward compatibility: grupos_conhecidos=None preserva Story 2.4
# ---------------------------------------------------------------------------


def test_extra_c_plagio_sem_grupos_preserva_comportamento_story_2_4() -> None:
    """AC-05 — chamada sem ``grupos_conhecidos`` é idêntica à Story 2.4."""
    texto_a = "A entropia mede a desordem em um sistema termodinâmico fechado."
    texto_b = "A entropia mede a desordem em um sistema termodinâmico fechado."
    trabalhos = [
        TrabalhoParaComparacao(aluno_id="A01", texto=texto_a),
        TrabalhoParaComparacao(aluno_id="C01", texto=texto_b),
    ]
    # Default — sem grupos_conhecidos
    pares_default = detectar_plagio_no_batch(trabalhos)
    # Explicit None
    pares_none = detectar_plagio_no_batch(trabalhos, grupos_conhecidos=None)

    assert len(pares_default) == len(pares_none) == 1
    assert pares_default[0].similaridade == pares_none[0].similaridade
    assert pares_default[0].severidade == "vermelho"  # sim=1.0
