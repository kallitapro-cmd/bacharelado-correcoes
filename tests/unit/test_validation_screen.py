"""Testes unitários da tela de validação (Story 3.2).

Cobre as funções puras de lógica sem instanciar Streamlit.
AC-17: pelo menos 5 testes cobrindo os cenários especificados.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from packages.wrapper.schemas import FichaCorrecao

from src.batch.group_detector import GrupoCandidato
from src.batch.plagiarism_detector import ParPlagio
from src.ui.validation_screen import (
    aplicar_filtro,
    calcular_alertas_pendentes,
    calcular_alunos_sem_alertas_pendentes,
    construir_linha_aluno,
    exportacao_liberada,
    registrar_decisao,
    resumo_contagens,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ra(i: int) -> str:
    return f"2026{i:07d}"


def _ficha(
    i: int,
    nota_calibrada: float = 7.0,
    nota_bruta: float | None = None,
    confianca: str = "alta",
    flags: list[str] | None = None,
) -> FichaCorrecao:
    """Cria FichaCorrecao para testes.

    nota_a1 = nota calibrada (padrão do calibrador).
    nota_a2 = nota bruta original (None quando não disponível).
    """
    return FichaCorrecao(
        ra=_ra(i),
        nota_a1=nota_calibrada,
        nota_a2=nota_bruta,
        feedback=f"Feedback aluno {i}",
        confianca=confianca,  # type: ignore[arg-type]
        flags=flags or [],
    )


def _par_plagio(ra_a: str, ra_b: str, sim: float) -> ParPlagio:
    sev = "vermelho" if sim >= 0.90 else "amarelo"
    return ParPlagio(aluno_a=ra_a, aluno_b=ra_b, similaridade=sim, severidade=sev)


def _grupo(membros: list[str], confianca: str = "media") -> GrupoCandidato:
    return GrupoCandidato(
        membros=membros,
        confianca=confianca,  # type: ignore[arg-type]
        razao_confianca="Menção mútua detectada.",
    )


# ---------------------------------------------------------------------------
# TC-01: construção correta das colunas a partir de fichas mockadas (AC-17-a)
# ---------------------------------------------------------------------------


class TestConstruirLinhaAluno:
    def test_colunas_basicas_sem_alertas(self) -> None:
        ficha = _ficha(1, nota_calibrada=8.5, nota_bruta=8.0)
        linha = construir_linha_aluno(ficha, alertas_plagio=[], grupos_candidatos=[])

        assert linha["ra"] == _ra(1)
        assert linha["nota_calibrada"] == pytest.approx(8.5)
        assert linha["nota_bruta"] == pytest.approx(8.0)
        assert linha["delta"] == pytest.approx(0.5)
        assert linha["tem_alerta"] is False
        assert linha["icones_alerta"] == []

    def test_icone_plagio_severo(self) -> None:
        ra = _ra(1)
        ficha = _ficha(1)
        par = _par_plagio(ra, _ra(2), sim=0.90)
        linha = construir_linha_aluno(ficha, alertas_plagio=[par], grupos_candidatos=[])

        assert "🔴" in linha["icones_alerta"]
        assert "🟡" not in linha["icones_alerta"]  # severo subsume moderado (AC-02)
        assert linha["tem_plagio_severo"] is True
        assert linha["tem_alerta"] is True

    def test_icone_plagio_moderado_sem_severo(self) -> None:
        ra = _ra(1)
        ficha = _ficha(1)
        par = _par_plagio(ra, _ra(2), sim=0.75)
        linha = construir_linha_aluno(ficha, alertas_plagio=[par], grupos_candidatos=[])

        assert "🟡" in linha["icones_alerta"]
        assert "🔴" not in linha["icones_alerta"]
        assert linha["tem_plagio_moderado"] is True

    def test_icone_grupo_coexiste_com_plagio(self) -> None:
        ra = _ra(1)
        ficha = _ficha(1)
        par = _par_plagio(ra, _ra(2), sim=0.75)
        grupo = _grupo(membros=[ra, _ra(2)])
        linha = construir_linha_aluno(ficha, alertas_plagio=[par], grupos_candidatos=[grupo])

        assert "🟡" in linha["icones_alerta"]
        assert "👥" in linha["icones_alerta"]

    def test_status_badge_top_10_pct(self) -> None:
        ficha = _ficha(1, nota_calibrada=9.5)
        linha = construir_linha_aluno(ficha, alertas_plagio=[], grupos_candidatos=[])
        assert linha["status_badge"] == "Top 10%"

    def test_status_badge_cap_9(self) -> None:
        ficha = _ficha(1, nota_calibrada=9.0, nota_bruta=9.5)
        linha = construir_linha_aluno(ficha, alertas_plagio=[], grupos_candidatos=[])
        assert linha["status_badge"] == "Cap 9"

    def test_status_badge_normal(self) -> None:
        ficha = _ficha(1, nota_calibrada=7.0, nota_bruta=7.0)
        linha = construir_linha_aluno(ficha, alertas_plagio=[], grupos_candidatos=[])
        assert linha["status_badge"] == "Normal"


# ---------------------------------------------------------------------------
# TC-02: filtro "Com alertas" retorna somente alunos com alertas (AC-17-b)
# ---------------------------------------------------------------------------


class TestAplicarFiltro:
    def _linhas(self) -> list[dict]:
        ra1 = _ra(1)
        ra2 = _ra(2)
        ficha1 = _ficha(1, nota_calibrada=7.0)
        ficha2 = _ficha(2, nota_calibrada=9.5)  # Top 10%
        ficha3 = _ficha(3, nota_calibrada=8.0)
        par = _par_plagio(ra1, ra2, sim=0.80)
        linhas = [
            construir_linha_aluno(ficha1, alertas_plagio=[par], grupos_candidatos=[]),
            construir_linha_aluno(ficha2, alertas_plagio=[], grupos_candidatos=[]),
            construir_linha_aluno(ficha3, alertas_plagio=[], grupos_candidatos=[]),
        ]
        return linhas

    def test_filtro_todos(self) -> None:
        linhas = self._linhas()
        resultado = aplicar_filtro(linhas, "Todos")
        assert len(resultado) == 3

    def test_filtro_com_alertas(self) -> None:
        linhas = self._linhas()
        resultado = aplicar_filtro(linhas, "Com alertas")
        assert len(resultado) == 1
        assert resultado[0]["ra"] == _ra(1)

    def test_filtro_top_10_pct(self) -> None:
        linhas = self._linhas()
        resultado = aplicar_filtro(linhas, "Top 10%")
        assert len(resultado) == 1
        assert resultado[0]["ra"] == _ra(2)

    def test_filtro_normal(self) -> None:
        linhas = self._linhas()
        resultado = aplicar_filtro(linhas, "Normal")
        assert all(row["status_badge"] == "Normal" for row in resultado)


# ---------------------------------------------------------------------------
# TC-03: batch approval aprova apenas alunos sem alertas, gera entrada por aluno
# (AC-17-c)
# ---------------------------------------------------------------------------


class TestBatchApproval:
    def test_sem_alertas_pendentes_exclui_com_alertas(self) -> None:
        ra_sem = _ra(1)
        ra_com = _ra(2)
        ficha_sem = _ficha(1, nota_calibrada=7.0)
        ficha_com = _ficha(2, nota_calibrada=6.5)
        par = _par_plagio(ra_com, _ra(3), sim=0.80)

        linhas = [
            construir_linha_aluno(ficha_sem, alertas_plagio=[], grupos_candidatos=[]),
            construir_linha_aluno(ficha_com, alertas_plagio=[par], grupos_candidatos=[]),
        ]
        decisoes: dict = {}

        candidatos = calcular_alunos_sem_alertas_pendentes(linhas, decisoes)
        assert len(candidatos) == 1
        assert candidatos[0]["ra"] == ra_sem

    def test_batch_gera_entrada_por_aluno(self) -> None:
        fichas = [_ficha(i, nota_calibrada=7.0) for i in range(1, 5)]
        linhas = [construir_linha_aluno(f, alertas_plagio=[], grupos_candidatos=[]) for f in fichas]
        decisoes: dict = {}

        candidatos = calcular_alunos_sem_alertas_pendentes(linhas, decisoes)
        for candidato in candidatos:
            decisoes[candidato["ra"]] = registrar_decisao(
                ra=candidato["ra"],
                acao="aprovado_lote",
                nota_final=candidato["nota_calibrada"],
            )

        assert len(decisoes) == 4
        for i in range(1, 5):
            assert _ra(i) in decisoes
            assert decisoes[_ra(i)]["acao"] == "aprovado_lote"

    def test_batch_nao_afeta_ja_decididos(self) -> None:
        ra_ja_decidido = _ra(1)
        fichas = [_ficha(i, nota_calibrada=7.0) for i in range(1, 4)]
        linhas = [construir_linha_aluno(f, alertas_plagio=[], grupos_candidatos=[]) for f in fichas]
        decisoes: dict = {ra_ja_decidido: registrar_decisao(ra_ja_decidido, "aprovado", 7.0)}

        candidatos = calcular_alunos_sem_alertas_pendentes(linhas, decisoes)
        assert all(c["ra"] != ra_ja_decidido for c in candidatos)


# ---------------------------------------------------------------------------
# TC-04: exportação bloqueada quando há alertas sem decisão (AC-17-d)
# ---------------------------------------------------------------------------


class TestControleExportacao:
    def _linhas_com_e_sem_alertas(self) -> list[dict]:
        ra_com = _ra(1)
        ficha_com = _ficha(1)
        par = _par_plagio(ra_com, _ra(2), sim=0.80)
        ficha_sem = _ficha(2)
        return [
            construir_linha_aluno(ficha_com, alertas_plagio=[par], grupos_candidatos=[]),
            construir_linha_aluno(ficha_sem, alertas_plagio=[], grupos_candidatos=[]),
        ]

    def test_exportacao_bloqueada_sem_decisoes(self) -> None:
        linhas = self._linhas_com_e_sem_alertas()
        decisoes: dict = {}
        assert exportacao_liberada(linhas, decisoes) is False

    def test_exportacao_bloqueada_apenas_sem_alertas_decididos(self) -> None:
        linhas = self._linhas_com_e_sem_alertas()
        # Só o aluno sem alerta foi decidido — o com alerta continua pendente
        decisoes: dict = {_ra(2): registrar_decisao(_ra(2), "aprovado", 7.0)}
        assert exportacao_liberada(linhas, decisoes) is False

    def test_exportacao_liberada_todos_alertas_decididos(self) -> None:
        linhas = self._linhas_com_e_sem_alertas()
        # Aluno com alerta decidido (via aprovação)
        decisoes: dict = {_ra(1): registrar_decisao(_ra(1), "aprovado", 6.5)}
        assert exportacao_liberada(linhas, decisoes) is True

    def test_alertas_pendentes_contagem_correta(self) -> None:
        linhas = self._linhas_com_e_sem_alertas()
        decisoes: dict = {}
        pendentes = calcular_alertas_pendentes(linhas, decisoes)
        assert len(pendentes) == 1
        assert pendentes[0]["ra"] == _ra(1)


# ---------------------------------------------------------------------------
# TC-05: exportação liberada quando revisão_manual é decisão válida (AC-17-e)
# ---------------------------------------------------------------------------


class TestRevisaoManualComoDecisao:
    def test_revisao_manual_libera_exportacao(self) -> None:
        ra_com = _ra(1)
        ficha_com = _ficha(1)
        par = _par_plagio(ra_com, _ra(2), sim=0.90)
        linhas = [
            construir_linha_aluno(ficha_com, alertas_plagio=[par], grupos_candidatos=[]),
        ]
        decisoes: dict = {
            ra_com: registrar_decisao(ra_com, "revisao_manual", ficha_com.nota_a1 or 0.0)
        }
        assert exportacao_liberada(linhas, decisoes) is True

    def test_revisao_manual_nao_conta_como_aprovado_na_contagem(self) -> None:
        ra = _ra(1)
        ficha = _ficha(1)
        par = _par_plagio(ra, _ra(2), sim=0.90)
        linhas = [construir_linha_aluno(ficha, alertas_plagio=[par], grupos_candidatos=[])]
        decisoes: dict = {ra: registrar_decisao(ra, "revisao_manual", 7.0)}

        contagens = resumo_contagens(linhas, decisoes)
        assert contagens["revisao_manual"] == 1
        assert contagens["aprovados"] == 0

    def test_decisao_registra_timestamp_iso8601(self) -> None:
        ra = _ra(1)
        decisao = registrar_decisao(ra, "aprovado", 8.0)
        # Valida que timestamp é parseável como ISO 8601
        dt = datetime.fromisoformat(decisao["timestamp"])
        assert dt.tzinfo is not None  # deve ter timezone

    def test_decisao_com_observacao(self) -> None:
        ra = _ra(1)
        decisao = registrar_decisao(ra, "editado", 7.5, observacao="Nota ajustada por critério X.")
        assert decisao["observacao"] == "Nota ajustada por critério X."

    def test_decisao_sem_observacao_string_vazia(self) -> None:
        ra = _ra(1)
        decisao = registrar_decisao(ra, "aprovado", 8.0)
        assert decisao["observacao"] == ""
