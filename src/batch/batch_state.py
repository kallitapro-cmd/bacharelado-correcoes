"""Estado intermediário de batch via sqlite3 efêmero (Story 2.6).

Isola toda lógica de banco de dados do batch_processor.py, tornando-o
testável com mocks simples sem tocar sqlite3 real.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# EFÊMERO: dados perdidos ao reiniciar sessão — comportamento esperado (ADR-004)
DB_PATH = Path("/tmp/batch_state.db")  # NUNCA usar caminho relativo ao projeto


# ---------------------------------------------------------------------------
# DDL — Schema das 3 tabelas obrigatórias (AC-02, AC-08)
# ---------------------------------------------------------------------------

_DDL_BATCHES = """
CREATE TABLE IF NOT EXISTS batches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id    TEXT    NOT NULL,
    total_alunos INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'em_andamento',
    criado_em    TEXT    NOT NULL
)
"""

_DDL_LOTES = """
CREATE TABLE IF NOT EXISTS lotes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    INTEGER NOT NULL,
    lote_num    INTEGER NOT NULL,
    total       INTEGER NOT NULL DEFAULT 0,
    processados INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'processado',
    erro_msg    TEXT
)
"""

# AC-08 — coluna "nome" explicitamente ausente; apenas "ra" identifica o aluno (ADR-004)
_DDL_FICHAS = """
CREATE TABLE IF NOT EXISTS fichas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     INTEGER NOT NULL,
    ra           TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'processado',
    ficha_json   TEXT    NOT NULL,
    criado_em    TEXT    NOT NULL,
    atualizado_em TEXT   NOT NULL
)
"""


def inicializar_banco() -> None:
    """Cria as 3 tabelas se não existirem — idempotente (AC-02)."""
    with sqlite3.connect(DB_PATH) as conn:  # AC-07 — context manager obrigatório
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_DDL_BATCHES)
        conn.execute(_DDL_LOTES)
        conn.execute(_DDL_FICHAS)
        conn.commit()


def criar_batch(sessao_id: str, total_alunos: int) -> int:
    """Cria registro de batch e retorna o batch_id gerado."""
    agora = datetime.now(UTC).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO batches (sessao_id, total_alunos, status, criado_em) "
            "VALUES (?, ?, 'em_andamento', ?)",
            (sessao_id, total_alunos, agora),
        )
        conn.commit()
        return cursor.lastrowid or 0


def salvar_lote(
    batch_id: int,
    lote_num: int,
    fichas: list[Any],
) -> None:
    """Persiste fichas do lote no banco com status 'processado' (AC-03).

    Cada ficha é serializada via model_dump_json() (Pydantic v2).
    """
    agora = datetime.now(UTC).isoformat()
    rows = []
    for ficha in fichas:
        try:
            ficha_json = ficha.model_dump_json()
        except AttributeError:
            ficha_json = json.dumps(ficha if isinstance(ficha, dict) else vars(ficha))
        rows.append((batch_id, ficha.ra, "processado", ficha_json, agora, agora))

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT INTO fichas (batch_id, ra, status, ficha_json, criado_em, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO lotes (batch_id, lote_num, total, processados, status) "
            "VALUES (?, ?, ?, ?, 'processado')",
            (batch_id, lote_num, len(fichas), len(fichas)),
        )
        conn.commit()


def marcar_lote_falha(batch_id: int, lote_num: int, motivo: str) -> None:
    """Registra falha do lote sem lançar exceção — falha silenciosa tolerada (AC-04)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lotes "
                "(batch_id, lote_num, total, processados, status, erro_msg) "
                "VALUES (?, ?, 0, 0, 'falha', ?)",
                (batch_id, lote_num, motivo),
            )
            conn.commit()
    except sqlite3.Error as e:  # AC-10 — except tipado (MNT-001)
        logger.warning(
            "Falha ao registrar erro do lote batch_id=%s lote=%s: %s", batch_id, lote_num, e
        )


def recuperar_fichas_batch(batch_id: int) -> list[Any]:
    """Retorna todas as fichas de um batch como lista de dicts deserializados (AC-05).

    Retorna dicts em vez de FichaCorrecao para evitar dependência circular com
    packages/wrapper/schemas.py nesta camada de infraestrutura.
    Quem precisar de FichaCorrecao deve fazer a conversão na camada de cima.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT ficha_json FROM fichas WHERE batch_id = ? ORDER BY id",
            (batch_id,),
        )
        rows = cursor.fetchall()

    fichas = []
    for (ficha_json,) in rows:
        try:
            fichas.append(json.loads(ficha_json))
        except json.JSONDecodeError as e:  # AC-10 — except tipado (MNT-001)
            logger.warning("Falha ao deserializar ficha_json: %s", e)
    return fichas


def limpar_banco() -> None:
    """Remove todos os registros de todas as tabelas (AC-06).

    Chamado ao iniciar novo batch para evitar acúmulo de dados em /tmp/.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM fichas")
        conn.execute("DELETE FROM lotes")
        conn.execute("DELETE FROM batches")
        conn.commit()
