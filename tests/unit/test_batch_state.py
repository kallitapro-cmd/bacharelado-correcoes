"""Testes unitários de batch_state.py — Story 2.6.

Todos os testes usam tmp_path + monkeypatch para sobrescrever DB_PATH.
Nunca escrevem em /tmp/batch_state.db real (AC-09).
Referências: ADR-004 (retenção zero), MNT-001 (except tipado).
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

import src.batch.batch_state as bstate
from src.batch.batch_state import (
    inicializar_banco,
    limpar_banco,
    marcar_lote_falha,
    recuperar_fichas_batch,
    salvar_lote,
)

# ---------------------------------------------------------------------------
# Fixture: redireciona DB_PATH para tmp_path isolado por teste
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db_isolado(tmp_path, monkeypatch):
    db = tmp_path / "test_batch_state.db"
    monkeypatch.setattr(bstate, "DB_PATH", db)
    yield db


# ---------------------------------------------------------------------------
# Helper: criar ficha mock compatível com salvar_lote
# ---------------------------------------------------------------------------


def _ficha(ra: str, nota: float = 7.0) -> SimpleNamespace:
    """Cria ficha mock com model_dump_json() compatível."""
    data = {
        "ra": ra,
        "nota_a1": nota,
        "feedback": "Feedback de teste.",
        "confianca": "alta",
        "flags": [],
    }

    def model_dump_json() -> str:
        return json.dumps(data)

    obj = SimpleNamespace(**data, model_dump_json=model_dump_json)
    return obj


# ---------------------------------------------------------------------------
# CT-01 — inicializar_banco() é idempotente
# ---------------------------------------------------------------------------


def test_ct01_inicializar_banco_idempotente(tmp_path):
    inicializar_banco()
    inicializar_banco()  # segunda chamada não deve lançar exceção

    with sqlite3.connect(bstate.DB_PATH) as conn:
        tabelas = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert {"batches", "lotes", "fichas"} <= tabelas


# ---------------------------------------------------------------------------
# CT-02 — salvar_lote() persiste fichas
# ---------------------------------------------------------------------------


def test_ct02_salvar_lote_persiste_fichas():
    inicializar_banco()
    fichas = [_ficha("20260100001"), _ficha("20260100002")]

    salvar_lote(batch_id=1, lote_num=0, fichas=fichas)

    with sqlite3.connect(bstate.DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fichas WHERE batch_id = 1").fetchone()[0]
        rows = conn.execute(
            "SELECT ra, ficha_json FROM fichas WHERE batch_id = 1 ORDER BY id"
        ).fetchall()

    assert count == 2
    assert rows[0][0] == "20260100001"
    assert rows[1][0] == "20260100002"
    # JSON deve ser deserializável
    assert json.loads(rows[0][1])["ra"] == "20260100001"


# ---------------------------------------------------------------------------
# CT-03 — recuperar_fichas_batch() deserializa corretamente
# ---------------------------------------------------------------------------


def test_ct03_recuperar_fichas_batch_deserializa():
    inicializar_banco()
    fichas_originais = [_ficha("20260100003", nota=8.5), _ficha("20260100004", nota=6.0)]
    salvar_lote(batch_id=2, lote_num=0, fichas=fichas_originais)

    resultado = recuperar_fichas_batch(batch_id=2)

    assert len(resultado) == 2
    ras = {f["ra"] for f in resultado}
    assert "20260100003" in ras
    assert "20260100004" in ras
    nota_003 = next(f["nota_a1"] for f in resultado if f["ra"] == "20260100003")
    assert nota_003 == pytest.approx(8.5)


# ---------------------------------------------------------------------------
# CT-04 — marcar_lote_falha() registra erro sem lançar exceção
# ---------------------------------------------------------------------------


def test_ct04_marcar_lote_falha_sem_excecao():
    inicializar_banco()

    marcar_lote_falha(batch_id=3, lote_num=0, motivo="timeout na API")  # não deve lançar

    with sqlite3.connect(bstate.DB_PATH) as conn:
        row = conn.execute(
            "SELECT status, erro_msg FROM lotes WHERE batch_id = 3 AND lote_num = 0"
        ).fetchone()

    assert row is not None
    assert row[0] == "falha"
    assert row[1] == "timeout na API"


# ---------------------------------------------------------------------------
# CT-05 — limpar_banco() remove todos os registros
# ---------------------------------------------------------------------------


def test_ct05_limpar_banco_remove_tudo():
    inicializar_banco()
    salvar_lote(batch_id=4, lote_num=0, fichas=[_ficha("20260100005")])
    marcar_lote_falha(batch_id=4, lote_num=1, motivo="erro")

    limpar_banco()

    with sqlite3.connect(bstate.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fichas").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM lotes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# CT-06 — context manager sem leak de conexão
# ---------------------------------------------------------------------------


def test_ct06_context_manager_sem_leak():
    inicializar_banco()
    salvar_lote(batch_id=5, lote_num=0, fichas=[_ficha("20260100006")])
    recuperar_fichas_batch(batch_id=5)

    # Após operações, DB não deve estar bloqueado — nova conexão deve abrir normalmente
    with sqlite3.connect(bstate.DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fichas WHERE batch_id = 5").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# CT-07 — schema sem coluna de nome de aluno (ADR-004)
# ---------------------------------------------------------------------------


def test_ct07_schema_sem_coluna_nome():
    inicializar_banco()

    with sqlite3.connect(bstate.DB_PATH) as conn:
        colunas = {row[1].lower() for row in conn.execute("PRAGMA table_info(fichas)").fetchall()}

    # AC-08 — nenhuma coluna de identificação pessoal pelo nome
    proibidas = {"nome", "nome_aluno", "name", "student_name"}
    assert not colunas & proibidas, f"Colunas proibidas encontradas: {colunas & proibidas}"
    assert "ra" in colunas  # RA é o único identificador permitido
