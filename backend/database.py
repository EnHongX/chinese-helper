import sqlite3
from pathlib import Path


def initialize_database(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature TEXT NOT NULL DEFAULT 'hanzi',
                query TEXT NOT NULL,
                characters TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        _ensure_column(
            conn,
            "query_history",
            "feature",
            "TEXT NOT NULL DEFAULT 'hanzi'",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_query_history_created_at ON query_history(created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                characters TEXT NOT NULL,
                total_count INTEGER NOT NULL,
                current_index INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_session_result (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL DEFAULT 1,
                char_index INTEGER NOT NULL,
                character TEXT NOT NULL,
                correct INTEGER NOT NULL DEFAULT 0,
                wrong_attempts INTEGER NOT NULL DEFAULT 0,
                answered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(session_id, char_index)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                characters TEXT NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_characters TEXT NOT NULL DEFAULT '',
                accuracy REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dictation_history_created_at ON dictation_history(created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_session_state (
                session_id INTEGER PRIMARY KEY CHECK (session_id = 1),
                char_index INTEGER NOT NULL,
                wrong_attempts INTEGER NOT NULL DEFAULT 0,
                last_answer TEXT NOT NULL DEFAULT '',
                is_correct INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def _ensure_column(conn, table_name, column_name, definition):
    columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )
