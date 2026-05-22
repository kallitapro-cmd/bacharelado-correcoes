"""Testes unitários das funções puras de progress_screen.py (Story 3.1).

Cobre AC-09 (a, b, c) + funções auxiliares de progresso e formatação.
Não exercita o ``render()`` diretamente — esse é integração Streamlit e
ficará coberto por testes manuais (DoD) e pela Story 3.4.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

import src.batch.batch_state as bstate
import src.ui.progress_screen as ps
from src.batch.exceptions import OrcamentoExcedidoError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db_isolado(tmp_path, monkeypatch):
    """Redireciona ``DB_PATH`` para sandbox por teste — nunca toca /tmp real."""
    db = tmp_path / "test_progress_screen.db"
    monkeypatch.setattr(bstate, "DB_PATH", db)
    yield db


def _seed_lotes(
    db_path,
    batch_id: int = 1,
    n_processados: int = 0,
    n_falhas: int = 0,
    alunos_por_lote: int = 12,
    motivos: list[str] | None = None,
) -> None:
    """Insere lotes simulados via DDL real do batch_state."""
    bstate.inicializar_banco()
    with sqlite3.connect(db_path) as conn:
        for i in range(n_processados):
            conn.execute(
                "INSERT INTO lotes (batch_id, lote_num, total, processados, status) "
                "VALUES (?, ?, ?, ?, 'processado')",
                (batch_id, i + 1, alunos_por_lote, alunos_por_lote),
            )
        motivos_lista = motivos or [f"erro_{i}" for i in range(n_falhas)]
        for i in range(n_falhas):
            conn.execute(
                "INSERT INTO lotes (batch_id, lote_num, total, processados, status, erro_msg) "
                "VALUES (?, ?, 0, 0, 'falha', ?)",
                (batch_id, 100 + i, motivos_lista[i] if i < len(motivos_lista) else "erro"),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# AC-09(c) — calcular_progresso para N lotes com K concluídos
# ---------------------------------------------------------------------------


class TestCalcularProgresso:
    def test_zero_lotes_concluidos_retorna_zero(self) -> None:
        assert ps.calcular_progresso(0, 10) == 0.0

    def test_metade_lotes_retorna_meio(self) -> None:
        assert ps.calcular_progresso(5, 10) == 0.5

    def test_todos_lotes_retorna_um(self) -> None:
        assert ps.calcular_progresso(10, 10) == 1.0

    def test_total_zero_retorna_zero(self) -> None:
        """Guard contra divisão por zero."""
        assert ps.calcular_progresso(0, 0) == 0.0
        assert ps.calcular_progresso(5, 0) == 0.0

    def test_concluidos_maior_que_total_satura_em_um(self) -> None:
        """Edge case: contador de lotes ficou estourado."""
        assert ps.calcular_progresso(15, 10) == 1.0

    def test_valores_negativos_retornam_zero(self) -> None:
        assert ps.calcular_progresso(-1, 10) == 0.0
        assert ps.calcular_progresso(5, -1) == 0.0

    def test_um_de_doze_aproximadamente(self) -> None:
        """Caso típico: 1 lote concluído de 12."""
        assert ps.calcular_progresso(1, 12) == pytest.approx(1 / 12)


# ---------------------------------------------------------------------------
# AC-01 — batch_config_valido
# ---------------------------------------------------------------------------


class TestBatchConfigValido:
    def test_config_none_retorna_false(self) -> None:
        assert ps.batch_config_valido(None) is False

    def test_config_nao_dict_retorna_false(self) -> None:
        assert ps.batch_config_valido("string") is False  # type: ignore[arg-type]
        assert ps.batch_config_valido([]) is False  # type: ignore[arg-type]

    def test_sem_alunos_retorna_false(self) -> None:
        assert ps.batch_config_valido({"enunciado": "Teste"}) is False

    def test_sem_enunciado_retorna_false(self) -> None:
        assert ps.batch_config_valido({"alunos": [{"ra": "1"}]}) is False

    def test_alunos_vazio_retorna_false(self) -> None:
        assert ps.batch_config_valido({"alunos": [], "enunciado": "Teste"}) is False

    def test_enunciado_vazio_retorna_false(self) -> None:
        assert ps.batch_config_valido({"alunos": [{"ra": "1"}], "enunciado": ""}) is False

    def test_enunciado_so_espacos_retorna_false(self) -> None:
        assert ps.batch_config_valido({"alunos": [{"ra": "1"}], "enunciado": "   "}) is False

    def test_config_minimo_valido_retorna_true(self) -> None:
        config = {"alunos": [{"ra": "00000000001"}], "enunciado": "Trabalho de filosofia"}
        assert ps.batch_config_valido(config) is True

    def test_config_completo_valido_retorna_true(self) -> None:
        config = {
            "alunos": [{"ra": "001"}, {"ra": "002"}],
            "enunciado": "Trabalho",
            "metadata": {"turma": "CC2025A"},
        }
        assert ps.batch_config_valido(config) is True

    def test_alunos_nao_lista_retorna_false(self) -> None:
        """``alunos`` deve ser ``list``; dict ou str é inválido."""
        assert ps.batch_config_valido({"alunos": {"ra": "1"}, "enunciado": "X"}) is False


# ---------------------------------------------------------------------------
# AC-04 — formatar_contador_lotes
# ---------------------------------------------------------------------------


class TestFormatarContadorLotes:
    def test_processando_no_meio(self) -> None:
        txt = ps.formatar_contador_lotes(3, 10, 36)
        assert "Processando lote 4 de 10" in txt
        assert "36 alunos corrigidos" in txt

    def test_inicio_processando_lote_1(self) -> None:
        txt = ps.formatar_contador_lotes(0, 10, 0)
        assert "Processando lote 1 de 10" in txt
        assert "0 alunos corrigidos" in txt

    def test_finalizado(self) -> None:
        txt = ps.formatar_contador_lotes(10, 10, 120)
        # Quando concluido, usa tempo presente
        assert "Lote 10 de 10" in txt
        assert "120 alunos corrigidos" in txt

    def test_total_zero(self) -> None:
        txt = ps.formatar_contador_lotes(0, 0, 0)
        assert "Aguardando" in txt

    def test_concluidos_maior_que_total_satura(self) -> None:
        txt = ps.formatar_contador_lotes(15, 10, 120)
        assert "Lote 10 de 10" in txt  # não estoura


# ---------------------------------------------------------------------------
# AC-07 — construir_batch_results
# ---------------------------------------------------------------------------


class TestConstruirBatchResults:
    def test_estrutura_completa(self) -> None:
        resultado = {
            "resultados": [],
            "custo_estimado_brl": 3.45,
            "lotes_processados": 5,
            "lotes_com_erro": 1,
        }
        fichas_cal = [MagicMock(), MagicMock()]
        plagio = [MagicMock()]
        grupos = []

        out = ps.construir_batch_results(resultado, fichas_cal, plagio, grupos)

        assert set(out.keys()) == {
            "fichas_calibradas",
            "alertas_plagio",
            "grupos_candidatos",
            "custo_estimado_brl",
            "lotes_com_erro",
        }
        assert out["fichas_calibradas"] is fichas_cal
        assert out["alertas_plagio"] is plagio
        assert out["grupos_candidatos"] is grupos
        assert out["custo_estimado_brl"] == 3.45
        assert out["lotes_com_erro"] == 1

    def test_resultado_sem_custo_usa_zero(self) -> None:
        out = ps.construir_batch_results({}, [], [], [])
        assert out["custo_estimado_brl"] == 0.0
        assert out["lotes_com_erro"] == 0

    def test_tipos_garantidos_float_int(self) -> None:
        """Garante coerção mesmo se vier string do batch_processor."""
        resultado = {"custo_estimado_brl": "5.0", "lotes_com_erro": "2"}
        out = ps.construir_batch_results(resultado, [], [], [])
        assert isinstance(out["custo_estimado_brl"], float)
        assert isinstance(out["lotes_com_erro"], int)
        assert out["custo_estimado_brl"] == 5.0
        assert out["lotes_com_erro"] == 2


# ---------------------------------------------------------------------------
# AC-03 — Polling SQL via contar_lotes_concluidos
# ---------------------------------------------------------------------------


class TestContarLotesConcluidos:
    def test_banco_inexistente_retorna_zero(self, tmp_path, monkeypatch) -> None:
        """Falha silenciosa quando o batch ainda não criou tabelas."""
        # DB_PATH aponta para arquivo que nem existe
        monkeypatch.setattr(bstate, "DB_PATH", tmp_path / "nao-existe.db")
        # NOTA: sqlite3.connect cria arquivo vazio mesmo sem tabelas — query falha
        # com OperationalError que é subclasse de sqlite3.Error → captura no try/except
        assert ps.contar_lotes_concluidos(1) == 0

    def test_zero_lotes_processados(self, _db_isolado) -> None:
        bstate.inicializar_banco()
        assert ps.contar_lotes_concluidos(1) == 0

    def test_tres_lotes_processados(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, batch_id=1, n_processados=3)
        assert ps.contar_lotes_concluidos(1) == 3

    def test_apenas_falhas_nao_conta(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, batch_id=1, n_processados=0, n_falhas=2)
        assert ps.contar_lotes_concluidos(1) == 0

    def test_outro_batch_id_isolado(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, batch_id=1, n_processados=5)
        _seed_lotes(_db_isolado, batch_id=2, n_processados=2)
        assert ps.contar_lotes_concluidos(1) == 5
        assert ps.contar_lotes_concluidos(2) == 2


class TestContarLotesComErro:
    def test_sem_falhas(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, n_processados=3)
        assert ps.contar_lotes_com_erro(1) == 0

    def test_com_duas_falhas(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, n_processados=3, n_falhas=2)
        assert ps.contar_lotes_com_erro(1) == 2


class TestListarMotivosFalha:
    def test_sem_falhas_retorna_vazio(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, n_processados=3)
        assert ps.listar_motivos_falha(1) == []

    def test_motivos_ordenados_por_lote_num(self, _db_isolado) -> None:
        _seed_lotes(
            _db_isolado,
            n_processados=0,
            n_falhas=3,
            motivos=["rate_limit_esgotado", "falha_validacao", "resposta_truncada"],
        )
        motivos = ps.listar_motivos_falha(1)
        assert len(motivos) == 3
        # _seed_lotes usa lote_num=100,101,102 para falhas → ordem crescente
        assert [m[0] for m in motivos] == [100, 101, 102]
        assert motivos[0][1] == "rate_limit_esgotado"


class TestContarAlunosCorrigidos:
    def test_zero_quando_vazio(self, _db_isolado) -> None:
        bstate.inicializar_banco()
        assert ps.contar_alunos_corrigidos(1) == 0

    def test_soma_processados(self, _db_isolado) -> None:
        _seed_lotes(_db_isolado, n_processados=3, alunos_por_lote=12)
        assert ps.contar_alunos_corrigidos(1) == 36


# ---------------------------------------------------------------------------
# AC-09(b) — OrcamentoExcedidoError capturada no worker
# ---------------------------------------------------------------------------


class TestRunBatchOrcamentoExcedido:
    """AC-09(b): _run_batch captura OrcamentoExcedidoError no estado compartilhado."""

    def test_orcamento_excedido_grava_em_estado(self, monkeypatch) -> None:
        def _fake_processar_batch(**_kwargs: Any) -> dict:
            raise OrcamentoExcedidoError(estimativa_brl=25.0, limite_brl=15.0)

        monkeypatch.setattr(ps, "processar_batch", _fake_processar_batch)

        estado: dict[str, Any] = {
            "resultado": None,
            "erro_orcamento": None,
            "erro_generico": None,
        }
        config = {
            "alunos": [{"ra": "1"}],
            "enunciado": "T",
            "metadata": {},
        }

        ps._run_batch(config, estado)

        assert estado["resultado"] is None
        assert estado["erro_generico"] is None
        assert isinstance(estado["erro_orcamento"], OrcamentoExcedidoError)
        assert estado["erro_orcamento"].estimativa_brl == 25.0
        assert estado["erro_orcamento"].limite_brl == 15.0

    def test_excecao_generica_grava_em_erro_generico(self, monkeypatch) -> None:
        def _fake_processar_batch(**_kwargs: Any) -> dict:
            raise RuntimeError("API down")

        monkeypatch.setattr(ps, "processar_batch", _fake_processar_batch)

        estado: dict[str, Any] = {
            "resultado": None,
            "erro_orcamento": None,
            "erro_generico": None,
        }
        config = {"alunos": [{"ra": "1"}], "enunciado": "T", "metadata": {}}

        ps._run_batch(config, estado)

        assert estado["resultado"] is None
        assert estado["erro_orcamento"] is None
        assert isinstance(estado["erro_generico"], RuntimeError)
        assert "API down" in str(estado["erro_generico"])

    def test_sucesso_grava_resultado(self, monkeypatch) -> None:
        def _fake_processar_batch(**_kwargs: Any) -> dict:
            return {"resultados": [], "custo_estimado_brl": 1.5, "lotes_com_erro": 0}

        monkeypatch.setattr(ps, "processar_batch", _fake_processar_batch)

        estado: dict[str, Any] = {
            "resultado": None,
            "erro_orcamento": None,
            "erro_generico": None,
        }
        config = {"alunos": [{"ra": "1"}], "enunciado": "T", "metadata": {}}

        ps._run_batch(config, estado)

        assert estado["resultado"] == {
            "resultados": [],
            "custo_estimado_brl": 1.5,
            "lotes_com_erro": 0,
        }
        assert estado["erro_orcamento"] is None
        assert estado["erro_generico"] is None


# ---------------------------------------------------------------------------
# Helpers de adapter (alunos do batch → TrabalhoParaComparacao / AlunoRef)
# ---------------------------------------------------------------------------


class TestConstruirTrabalhosParaComparacao:
    def test_extrai_ra_e_resposta(self) -> None:
        alunos = [
            {"ra": "001", "resposta": "texto A", "turma": "CC1"},
            {"ra": "002", "resposta": "texto B"},
        ]
        trabalhos = ps._construir_trabalhos_para_comparacao(alunos)
        assert len(trabalhos) == 2
        assert trabalhos[0].aluno_id == "001"
        assert trabalhos[0].texto == "texto A"
        assert trabalhos[1].aluno_id == "002"
        assert trabalhos[1].texto == "texto B"


class TestConstruirAlunosRef:
    def test_associa_nome_via_nomes_por_ra(self) -> None:
        alunos = [{"ra": "001"}, {"ra": "002"}, {"ra": "003"}]
        nomes = {"001": "Ana Silva", "002": "Bruno Souza"}
        refs = ps._construir_alunos_ref(alunos, nomes)
        # Aluno 003 não tem nome → omitido
        assert len(refs) == 2
        assert refs[0].ra == "001"
        assert refs[0].nome == "Ana Silva"
        assert refs[1].ra == "002"
        assert refs[1].nome == "Bruno Souza"

    def test_ra_vazio_ignorado(self) -> None:
        alunos = [{"ra": "", "resposta": "X"}, {"ra": "001"}]
        nomes = {"001": "Ana"}
        refs = ps._construir_alunos_ref(alunos, nomes)
        assert len(refs) == 1
        assert refs[0].ra == "001"
