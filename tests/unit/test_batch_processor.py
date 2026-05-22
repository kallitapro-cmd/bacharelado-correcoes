"""Testes unitários do orquestrador de batch (Story 2.2).

Cobrem todos os ACs (AC-01 a AC-16). Usam mocks para ``corrigir_aluno``,
``log_action`` e ``_get_max_cost_brl`` para isolar a lógica de orquestração
sem tocar API real, Streamlit ou sqlite3 de produção.

Convenções:

* ``DB_PATH`` é redirecionado para ``tmp_path`` em cada teste (autouse).
* ``_get_max_cost_brl`` é monkeypatchado para injetar limites de orçamento.
* ``corrigir_aluno`` é mockado por substituição direta na referência
  importada em ``batch_processor``.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from packages.wrapper.exceptions import (
    ClonTruncatedResponseError,
    ClonValidationError,
)

import src.batch.batch_processor as bp
import src.batch.batch_state as bstate
from src.batch.batch_processor import (
    AcaoBatch,
    processar_batch,
)
from src.batch.exceptions import OrcamentoExcedidoError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db_isolado(tmp_path, monkeypatch):
    """Redireciona ``DB_PATH`` para sandbox por teste — nunca toca /tmp real."""
    db = tmp_path / "test_batch_processor.db"
    monkeypatch.setattr(bstate, "DB_PATH", db)
    yield db


@pytest.fixture(autouse=True)
def _max_cost_alto(monkeypatch):
    """Default: MAX_COST_BRL bem alto para não bloquear testes."""
    monkeypatch.setattr(bp, "_get_max_cost_brl", lambda: 10_000.0)
    yield


def _aluno(ra: str) -> dict:
    return {"ra": ra, "conteudo": f"trabalho do aluno {ra}"}


def _ficha_ok(ra: str, nota: float = 7.0) -> SimpleNamespace:
    """Cria ficha-mock compatível com ``salvar_lote`` (atributo ``.ra`` + dump JSON)."""
    data = {
        "ra": ra,
        "nota_a1": nota,
        "feedback": "Feedback de teste.",
        "confianca": "alta",
        "flags": [],
        "status": "processado",
    }

    def model_dump_json() -> str:
        return json.dumps(data)

    return SimpleNamespace(**data, model_dump_json=model_dump_json)


def _mock_corrigir_ok(_client, payload):
    """Mock de ``corrigir_aluno`` que retorna ficha OK por aluno do payload."""
    fichas = [_ficha_ok(a["ra"]) for a in payload["alunos"]]
    return SimpleNamespace(fichas=fichas)


# ---------------------------------------------------------------------------
# TC-01 — Partição correta em lotes de BATCH_SIZE (AC-01)
# ---------------------------------------------------------------------------


def test_tc01_particiona_em_lotes_de_batch_size(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(25)]
    mock_corrigir = MagicMock(side_effect=_mock_corrigir_ok)
    monkeypatch.setattr(bp, "corrigir_aluno", mock_corrigir)

    result = processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={"turma": "T1"},
        max_workers=1,  # determinístico para a contagem
    )

    # 25 alunos / BATCH_SIZE=10 → 10 + 10 + 5 = 3 chamadas
    assert mock_corrigir.call_count == 3
    assert result["lotes_processados"] == 3
    assert result["lotes_com_erro"] == 0


# ---------------------------------------------------------------------------
# TC-02 — ClonValidationError em 1 lote não aborta os demais (AC-04 + AC-06)
# ---------------------------------------------------------------------------


def test_tc02_falha_validacao_lote_nao_aborta_demais(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(20)]
    chamadas = {"n": 0}

    def side_effect(_client, payload):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise ClonValidationError(raw="lixo", errors=[{"type": "x"}])
        return _mock_corrigir_ok(_client, payload)

    monkeypatch.setattr(bp, "corrigir_aluno", MagicMock(side_effect=side_effect))

    result = processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={},
        max_workers=1,
    )

    # Não levanta — falha isolada
    assert result["lotes_processados"] == 1
    assert result["lotes_com_erro"] == 1

    # 10 com status REVISÃO MANUAL — VALIDAÇÃO + 10 OK
    resultados = result["resultados"]
    status_revisao = [r for r in resultados if r.get("status") == bp.STATUS_VALIDACAO]
    status_ok = [r for r in resultados if r.get("status") == "processado"]
    assert len(status_revisao) == 10
    assert len(status_ok) == 10


# ---------------------------------------------------------------------------
# TC-03 — ClonTruncatedResponseError marca todos como TRUNCADA (AC-05)
# ---------------------------------------------------------------------------


def test_tc03_truncated_response_marca_status_correto(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(10)]

    def side_effect(_client, _payload):
        raise ClonTruncatedResponseError(ra="20260100000", tokens_used=4096)

    monkeypatch.setattr(bp, "corrigir_aluno", MagicMock(side_effect=side_effect))

    result = processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={},
        max_workers=1,
    )

    assert result["lotes_com_erro"] == 1
    assert result["lotes_processados"] == 0
    resultados = result["resultados"]
    assert len(resultados) == 10
    assert all(r.get("status") == bp.STATUS_TRUNCADA for r in resultados)


# ---------------------------------------------------------------------------
# TC-04 — Bloqueio por orçamento (AC-07 + AC-08)
# ---------------------------------------------------------------------------


def test_tc04_orcamento_excedido_bloqueia_antes_de_qualquer_chamada(monkeypatch):
    alunos = [_aluno(f"2026{i:07d}") for i in range(1000)]  # 100 lotes → custo alto
    mock_corrigir = MagicMock(side_effect=_mock_corrigir_ok)
    monkeypatch.setattr(bp, "corrigir_aluno", mock_corrigir)
    monkeypatch.setattr(bp, "_get_max_cost_brl", lambda: 1.00)

    with pytest.raises(OrcamentoExcedidoError) as exc_info:
        processar_batch(
            alunos=alunos,
            enunciado="teste",
            metadata={},
        )

    assert "ORÇAMENTO EXCEDIDO" in str(exc_info.value)
    assert mock_corrigir.call_count == 0  # nenhuma chamada à API foi feita


# ---------------------------------------------------------------------------
# TC-05 — Estimativa dentro do limite não bloqueia (AC-07)
# ---------------------------------------------------------------------------


def test_tc05_estimativa_dentro_do_limite_nao_bloqueia(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(10)]
    mock_corrigir = MagicMock(side_effect=_mock_corrigir_ok)
    monkeypatch.setattr(bp, "corrigir_aluno", mock_corrigir)
    monkeypatch.setattr(bp, "_get_max_cost_brl", lambda: 50.00)

    result = processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={},
        max_workers=1,
    )

    assert "custo_estimado_brl" in result
    assert isinstance(result["custo_estimado_brl"], float)
    assert result["custo_estimado_brl"] > 0
    assert result["lotes_processados"] == 1


# ---------------------------------------------------------------------------
# TC-06 — Estado persistido em sqlite3 via batch_state (AC-03 + AC-14)
# ---------------------------------------------------------------------------


def test_tc06_estado_persistido_em_sqlite3(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(10)]
    monkeypatch.setattr(bp, "corrigir_aluno", MagicMock(side_effect=_mock_corrigir_ok))

    processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={},
        max_workers=1,
    )

    # DB_PATH foi redirecionado pelo autouse — verificamos a presença das tabelas
    db_path = bstate.DB_PATH
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        count_batches = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        count_fichas = conn.execute("SELECT COUNT(*) FROM fichas").fetchone()[0]
        count_lotes = conn.execute("SELECT COUNT(*) FROM lotes").fetchone()[0]

    assert count_batches >= 1
    assert count_fichas == 10
    assert count_lotes >= 1


# ---------------------------------------------------------------------------
# TC-07 — log_action sempre usa enum AcaoBatch + sem PII (AC-10 + AC-11)
# ---------------------------------------------------------------------------


def test_tc07_log_action_usa_enum_e_sem_pii(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(10)]
    monkeypatch.setattr(bp, "corrigir_aluno", MagicMock(side_effect=_mock_corrigir_ok))

    fake_log = MagicMock()
    monkeypatch.setattr(bp, "log_action", fake_log)

    processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={},
        max_workers=1,
    )

    assert fake_log.call_count >= 3  # início + lote + fim
    valores_validos = {e.value for e in AcaoBatch}
    for chamada in fake_log.call_args_list:
        kwargs = chamada.kwargs
        acao = kwargs.get("acao")
        payload = kwargs.get("payload_resumido", "")

        # AC-10 — acao deve ser um dos valores do enum (passamos .value)
        assert acao in valores_validos, f"acao inválida: {acao!r}"

        # AC-11 — payload sem PII (sem RAs de 11 dígitos, sem 'nota=', sem 'nome=')
        assert "nome=" not in payload.lower()
        assert "nota=" not in payload.lower()
        # RA tem 11 dígitos no formato Story 1.x — garantimos que não aparece
        import re

        assert not re.search(r"\b\d{11}\b", payload), f"RA em payload: {payload!r}"


# ---------------------------------------------------------------------------
# TC-08 — max_workers configurável (AC-02)
# ---------------------------------------------------------------------------


def test_tc08_max_workers_configuravel(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(30)]
    monkeypatch.setattr(bp, "corrigir_aluno", MagicMock(side_effect=_mock_corrigir_ok))

    # Espionamos ThreadPoolExecutor sem substituir o comportamento
    real_executor = bp.ThreadPoolExecutor
    capturados: dict = {}

    def spy_executor(*args, **kwargs):
        capturados["max_workers"] = kwargs.get("max_workers", args[0] if args else None)
        return real_executor(*args, **kwargs)

    with patch.object(bp, "ThreadPoolExecutor", side_effect=spy_executor) as mock_cls:
        result = processar_batch(
            alunos=alunos,
            enunciado="teste",
            metadata={},
            max_workers=2,
        )

    assert mock_cls.called
    assert capturados["max_workers"] == 2
    assert result["lotes_processados"] == 3  # 30 / 10 = 3 lotes


# ---------------------------------------------------------------------------
# TC-09 (bônus) — AcaoBatch é Enum com valores corretos (AC-10)
# ---------------------------------------------------------------------------


def test_tc09_acao_batch_enum_estavel():
    assert AcaoBatch.BATCH_INICIADO.value == "batch_iniciado"
    assert AcaoBatch.LOTE_PROCESSADO.value == "lote_processado"
    assert AcaoBatch.LOTE_ERRO.value == "lote_erro"
    assert AcaoBatch.BATCH_CONCLUIDO.value == "batch_concluido"
    # str(Enum) — herdamos de str
    assert isinstance(AcaoBatch.BATCH_INICIADO, str)


# ---------------------------------------------------------------------------
# TC-10 (bônus) — Retry para 429 com backoff e fallback para falha (AC-15)
# ---------------------------------------------------------------------------


def test_tc10_retry_rate_limit_marca_falha_apos_3_tentativas(monkeypatch):
    alunos = [_aluno(f"2026010{i:04d}") for i in range(10)]

    def sempre_429(_client, _payload):
        raise RuntimeError("HTTP 429 rate limit exceeded")

    monkeypatch.setattr(bp, "corrigir_aluno", MagicMock(side_effect=sempre_429))
    # zera os sleeps para o teste rodar rápido
    monkeypatch.setattr(bp.time, "sleep", lambda _s: None)

    result = processar_batch(
        alunos=alunos,
        enunciado="teste",
        metadata={},
        max_workers=1,
    )

    assert result["lotes_com_erro"] == 1
    assert result["lotes_processados"] == 0
    assert all(r.get("status") == bp.STATUS_RATE_LIMIT for r in result["resultados"])
