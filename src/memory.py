"""
Memoria persistente de Mai-chan (capa 1 estructurada + capa 2 episódica).

Usa **SQLite de la stdlib** (`sqlite3`): sin servidor, sin dependencias — un solo
archivo local que el bot crea solo. Ver docs/plan_vision_general.md §8.

- `viewers`           → ¿quién es nuevo / recurrente? (un SELECT, no RAG)
- `agenda`            → plan de streams (de hoy y futuros), para la autonomía
- `stream_summaries`  → resúmenes por stream, para dar continuidad entre sesiones

La capa 3 (RAG semántico) NO está acá: se suma recién cuando el volumen de
recuerdos en lenguaje natural no entre en el contexto (cientos de streams).

Regla del plan: datos exactos → SQLite (acá); recuerdos en lenguaje natural
buscados por significado → RAG (más adelante).
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Dict, List, Optional

DB_FILENAME = "maichan_memory.db"


def _db_path() -> str:
    """Resuelve el archivo de la BD junto al resto de assets (BASE_DIR_PATH)."""
    base = os.environ.get("BASE_DIR_PATH", os.getcwd())
    return os.path.join(base, DB_FILENAME)


@contextmanager
def _connect():
    """Abre una conexión por operación (archivo local → barato) y commitea."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db() -> None:
    """Crea las tablas si no existen. Idempotente; llamar al arrancar el bot."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS viewers (
                user_id     TEXT PRIMARY KEY,
                name        TEXT,
                first_seen  TEXT,
                last_seen   TEXT,
                n_messages  INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS agenda (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha        TEXT,
                que_hacer    TEXT,
                sugerido_por TEXT,
                estado       TEXT DEFAULT 'pendiente'
            );
            CREATE TABLE IF NOT EXISTS stream_summaries (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha   TEXT,
                resumen TEXT
            );
            """
        )


# --- Viewers (capa 1: ¿nuevo o recurrente?) --------------------------------


def record_viewer(user_id: str, name: str) -> Dict:
    """Registra (o actualiza) un viewer. Devuelve `{nuevo: bool, n_messages: int}`."""
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT n_messages FROM viewers WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO viewers "
                "(user_id, name, first_seen, last_seen, n_messages) "
                "VALUES (?, ?, ?, ?, 1)",
                (user_id, name, now, now),
            )
            return {"nuevo": True, "n_messages": 1}
        n = row["n_messages"] + 1
        conn.execute(
            "UPDATE viewers SET name = ?, last_seen = ?, n_messages = ? "
            "WHERE user_id = ?",
            (name, now, n, user_id),
        )
        return {"nuevo": False, "n_messages": n}


# --- Agenda (capa 1: plan de streams, base de la autonomía) ----------------


def add_agenda(
    que_hacer: str, fecha: Optional[str] = None, sugerido_por: str = ""
) -> None:
    """Agenda una tarea/idea para un stream (hoy por defecto)."""
    fecha = fecha or date.today().isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO agenda (fecha, que_hacer, sugerido_por) VALUES (?, ?, ?)",
            (fecha, que_hacer, sugerido_por),
        )


def get_agenda(fecha: Optional[str] = None) -> List[str]:
    """Tareas pendientes de una fecha (hoy por defecto), en orden de carga."""
    fecha = fecha or date.today().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT que_hacer FROM agenda "
            "WHERE fecha = ? AND estado = 'pendiente' ORDER BY id",
            (fecha,),
        ).fetchall()
    return [r["que_hacer"] for r in rows]


# --- Resúmenes por stream (capa 2: memoria episódica) ----------------------


def save_summary(resumen: str, fecha: Optional[str] = None) -> None:
    """Guarda el resumen de un stream (se genera al cerrar la sesión)."""
    fecha = fecha or date.today().isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO stream_summaries (fecha, resumen) VALUES (?, ?)",
            (fecha, resumen),
        )


def get_recent_summaries(n: int = 3) -> List[str]:
    """Últimos N resúmenes en orden cronológico (más viejo primero)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT fecha, resumen FROM stream_summaries ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [f"{r['fecha']}: {r['resumen']}" for r in reversed(rows)]
