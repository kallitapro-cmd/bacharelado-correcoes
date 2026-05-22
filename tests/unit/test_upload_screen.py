"""Testes unitários das funções puras de upload_screen.py (Story 3.0).

Testa apenas lógica pura (sem st.*). Cobre AC-09 (a), (b), (c) e mais casos.
"""

from __future__ import annotations

import pandas as pd
from packages.wrapper.clone_client import BATCH_SIZE

from src.ui.upload_screen import (
    COLUNAS_OBRIGATORIAS,
    calcular_estimativa,
    construir_alunos,
    construir_nomes_por_ra,
    normalizar_colunas,
    validar_colunas,
    validar_pode_iniciar,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _df_valido(n: int = 3, com_turma: bool = True) -> pd.DataFrame:
    """DataFrame mínimo válido para testes."""
    data = {
        "ra": [f"0000{i:07d}" for i in range(1, n + 1)],
        "nome": [f"Aluno {i}" for i in range(1, n + 1)],
        "resposta": [f"Resposta do aluno {i}" for i in range(1, n + 1)],
    }
    if com_turma:
        data["turma"] = [f"CC{i}" for i in range(1, n + 1)]
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# AC-09(a) — planilha com colunas corretas → sem erro de validação
# ---------------------------------------------------------------------------


class TestValidarColunas:
    def test_colunas_corretas_retorna_lista_vazia(self) -> None:
        df = _df_valido()
        assert validar_colunas(df) == []

    def test_sem_coluna_ra_retorna_ra_ausente(self) -> None:
        """AC-09(b) — planilha sem coluna `ra` → erro de validação."""
        df = pd.DataFrame({"nome": ["A"], "resposta": ["R"]})
        ausentes = validar_colunas(df)
        assert "ra" in ausentes

    def test_sem_coluna_nome_retorna_nome_ausente(self) -> None:
        df = pd.DataFrame({"ra": ["00000000001"], "resposta": ["R"]})
        ausentes = validar_colunas(df)
        assert "nome" in ausentes

    def test_sem_coluna_resposta_retorna_resposta_ausente(self) -> None:
        df = pd.DataFrame({"ra": ["00000000001"], "nome": ["A"]})
        ausentes = validar_colunas(df)
        assert "resposta" in ausentes

    def test_multiplas_colunas_ausentes(self) -> None:
        df = pd.DataFrame({"turma": ["CC1"]})
        ausentes = validar_colunas(df)
        assert set(ausentes) == COLUNAS_OBRIGATORIAS

    def test_colunas_case_insensitive(self) -> None:
        df = pd.DataFrame({"RA": ["001"], "NOME": ["A"], "RESPOSTA": ["R"]})
        df_norm = normalizar_colunas(df)
        assert validar_colunas(df_norm) == []


# ---------------------------------------------------------------------------
# AC-09(c) — enunciado vazio → botão desabilitado
# ---------------------------------------------------------------------------


class TestValidarPodeIniciar:
    def test_tudo_ok_permite_iniciar(self) -> None:
        pode, motivo = validar_pode_iniciar(
            df_valido=True, enunciado="Enunciado válido", custo=5.0, max_cost=15.0
        )
        assert pode is True
        assert motivo == ""

    def test_enunciado_vazio_bloqueia(self) -> None:
        """AC-09(c) — enunciado vazio → botão desabilitado."""
        pode, motivo = validar_pode_iniciar(df_valido=True, enunciado="", custo=5.0, max_cost=15.0)
        assert pode is False
        assert motivo != ""

    def test_enunciado_so_espacos_bloqueia(self) -> None:
        pode, _ = validar_pode_iniciar(df_valido=True, enunciado="   ", custo=5.0, max_cost=15.0)
        assert pode is False

    def test_df_invalido_bloqueia(self) -> None:
        pode, motivo = validar_pode_iniciar(
            df_valido=False, enunciado="Enunciado", custo=5.0, max_cost=15.0
        )
        assert pode is False
        assert motivo != ""

    def test_custo_acima_limite_bloqueia(self) -> None:
        """AC-05 — custo excede MAX_COST_BRL → botão desabilitado."""
        pode, motivo = validar_pode_iniciar(
            df_valido=True, enunciado="Enunciado", custo=20.0, max_cost=15.0
        )
        assert pode is False
        assert "R$ 20.00" in motivo or "20" in motivo

    def test_custo_igual_limite_permite(self) -> None:
        pode, _ = validar_pode_iniciar(
            df_valido=True, enunciado="Enunciado", custo=15.0, max_cost=15.0
        )
        assert pode is True


# ---------------------------------------------------------------------------
# construir_alunos — garante ADR-004 (nome ausente do dict de alunos)
# ---------------------------------------------------------------------------


class TestConstruirAlunos:
    def test_alunos_sem_campo_nome(self) -> None:
        """AC-08 — dict `alunos` NÃO contém `nome` (ADR-004)."""
        df = normalizar_colunas(_df_valido())
        alunos = construir_alunos(df)
        for aluno in alunos:
            assert "nome" not in aluno

    def test_alunos_contem_ra_resposta_turma(self) -> None:
        df = normalizar_colunas(_df_valido())
        alunos = construir_alunos(df)
        assert len(alunos) == 3
        for aluno in alunos:
            assert "ra" in aluno
            assert "resposta" in aluno
            assert "turma" in aluno

    def test_alunos_sem_turma_na_planilha(self) -> None:
        df = normalizar_colunas(_df_valido(com_turma=False))
        alunos = construir_alunos(df)
        for aluno in alunos:
            assert aluno["turma"] == ""


# ---------------------------------------------------------------------------
# construir_nomes_por_ra — mapa auxiliar para preview/exportação
# ---------------------------------------------------------------------------


class TestConstruirNomesPorRa:
    def test_mapa_ra_para_nome(self) -> None:
        df = normalizar_colunas(_df_valido(n=2))
        nomes = construir_nomes_por_ra(df)
        assert len(nomes) == 2
        for ra, nome in nomes.items():
            assert isinstance(ra, str)
            assert isinstance(nome, str)

    def test_sem_coluna_nome_retorna_dict_vazio(self) -> None:
        df = pd.DataFrame({"ra": ["001"], "resposta": ["R"]})
        nomes = construir_nomes_por_ra(df)
        assert nomes == {}


# ---------------------------------------------------------------------------
# calcular_estimativa — usa BATCH_SIZE real do clone_client
# ---------------------------------------------------------------------------


class TestCalcularEstimativa:
    def test_zero_alunos_retorna_zero(self) -> None:
        assert calcular_estimativa(0) == 0.0

    def test_estimativa_positiva_para_alunos(self) -> None:
        estimativa = calcular_estimativa(30)
        assert estimativa > 0.0

    def test_lotes_calculados_corretamente(self) -> None:
        n = BATCH_SIZE * 2 + 1  # 3 lotes
        estimativa_3 = calcular_estimativa(n)
        estimativa_1 = calcular_estimativa(1)
        assert estimativa_3 > estimativa_1

    def test_turma_grande_nao_estoura(self) -> None:
        estimativa = calcular_estimativa(500)
        assert isinstance(estimativa, float)
        assert estimativa > 0
