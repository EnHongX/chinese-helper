import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SQLiteRepository:
    def __init__(self, db_path):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class HistoryRepository(SQLiteRepository):
    def create(self, feature, query, characters):
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO query_history (feature, query, characters) VALUES (?, ?, ?)",
                (feature, query, characters),
            )
            return cursor.lastrowid

    def list(self, limit=12):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, feature, query, characters, created_at
                FROM query_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, ids):
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM query_history WHERE id IN ({placeholders})",
                ids,
            )
        return cursor.rowcount

    def recent_characters(self, limit=200):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT characters FROM query_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row["characters"] for row in rows]


class DictationRepository(SQLiteRepository):
    def get_session(self):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM dictation_session WHERE id = 1"
            ).fetchone()
        return dict(row) if row else None

    def get_results(self):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT char_index, character, correct, wrong_attempts
                FROM dictation_session_result
                WHERE session_id = 1
                ORDER BY char_index
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_completion_results(self):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT character, correct, wrong_attempts
                FROM dictation_session_result
                WHERE session_id = 1
                ORDER BY char_index
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_state(self):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM dictation_session_state WHERE session_id = 1"
            ).fetchone()
        return dict(row) if row else None

    def get_state_for_index(self, char_index):
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT wrong_attempts
                FROM dictation_session_state
                WHERE session_id = 1 AND char_index = ?
                """,
                (char_index,),
            ).fetchone()
        return dict(row) if row else None

    def clear_session(self):
        with self.connect() as conn:
            conn.execute("DELETE FROM dictation_session_state WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session_result WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session WHERE id = 1")

    def create_session(self, characters):
        with self.connect() as conn:
            conn.execute("DELETE FROM dictation_session_state WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session_result WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session WHERE id = 1")
            conn.execute(
                """
                INSERT INTO dictation_session (id, characters, total_count, current_index)
                VALUES (1, ?, ?, 0)
                """,
                ("".join(characters), len(characters)),
            )

    def save_answer(self, position, correct_character, submitted_character, is_correct, wrong_attempts):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dictation_session_result
                   (session_id, char_index, character, correct, wrong_attempts)
                VALUES (1, ?, ?, ?, ?)
                """,
                (position, correct_character, 1 if is_correct else 0, wrong_attempts),
            )
            if is_correct:
                conn.execute(
                    "UPDATE dictation_session SET current_index = ? WHERE id = 1",
                    (position + 1,),
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO dictation_session_state
                   (session_id, char_index, wrong_attempts, last_answer, is_correct)
                VALUES (1, ?, ?, ?, ?)
                """,
                (position, wrong_attempts, submitted_character, 1 if is_correct else 0),
            )

    def add_history(self, characters, total_count, correct_count, wrong_characters, accuracy):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dictation_history
                   (characters, total_count, correct_count, wrong_characters, accuracy)
                VALUES (?, ?, ?, ?, ?)
                """,
                (characters, total_count, correct_count, wrong_characters, accuracy),
            )

    def list_history(self, limit=50):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dictation_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
