#!/usr/bin/env python3
import json
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "chinese_helper.sqlite3"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(query_history)").fetchall()
        }
        if "feature" not in columns:
            conn.execute(
                "ALTER TABLE query_history ADD COLUMN feature TEXT NOT NULL DEFAULT 'hanzi'"
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
                total_count INTEGER NOT NULL,
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


def is_hanzi(char):
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0x2CEB0 <= code <= 0x2EBEF
        or 0x30000 <= code <= 0x3134F
        or 0x31350 <= code <= 0x323AF
    )


def chinese_only(value):
    return "".join(char for char in value if is_hanzi(char))


def get_history_characters():
    """Get all unique characters from query history."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT characters FROM query_history ORDER BY id DESC LIMIT 200").fetchall()
    chars = []
    seen = set()
    for row in rows:
        for char in row[0]:
            if char not in seen and is_hanzi(char):
                chars.append(char)
                seen.add(char)
    return chars


class ChineseHelperHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        elif self.path.startswith("/data/generated/"):
            self.send_header("Cache-Control", "public, max-age=3600")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_list(parsed)
        elif parsed.path == "/api/dictation/characters":
            self.handle_dictation_characters()
        elif parsed.path == "/api/dictation/session":
            self.handle_dictation_session_get()
        elif parsed.path == "/api/dictation/history":
            self.handle_dictation_history_list()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_create()
        elif parsed.path == "/api/dictation/start":
            self.handle_dictation_start()
        elif parsed.path == "/api/dictation/answer":
            self.handle_dictation_answer()
        elif parsed.path == "/api/dictation/complete":
            self.handle_dictation_complete()
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_delete()
        elif parsed.path == "/api/dictation/session":
            self.handle_dictation_session_delete()
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def handle_history_list(self, parsed):
        params = parse_qs(parsed.query)
        raw_limit = params.get("limit", ["12"])[0]
        try:
            limit = min(max(int(raw_limit), 1), 50)
        except ValueError:
            limit = 12

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, feature, query, characters, created_at
                FROM query_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        self.send_json({"items": [dict(row) for row in rows]})

    def handle_history_create(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        query = str(payload.get("query", "")).strip()
        feature = str(payload.get("feature", "hanzi")).strip() or "hanzi"
        characters = chinese_only(str(payload.get("characters", "")))

        if not query or not characters:
            self.send_json(
                {"error": "query and characters are required"}, HTTPStatus.BAD_REQUEST
            )
            return

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "INSERT INTO query_history (feature, query, characters) VALUES (?, ?, ?)",
                (feature, query, characters),
            )
            history_id = cursor.lastrowid

        self.send_json(
            {
                "id": history_id,
                "feature": feature,
                "query": query,
                "characters": characters,
            },
            HTTPStatus.CREATED,
        )

    def handle_history_delete(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        ids = payload.get("ids", [])
        if not isinstance(ids, list):
            self.send_json({"error": "ids must be a list"}, HTTPStatus.BAD_REQUEST)
            return

        safe_ids = []
        for value in ids:
            try:
                safe_ids.append(int(value))
            except (TypeError, ValueError):
                continue

        if not safe_ids:
            self.send_json({"deleted": 0})
            return

        placeholders = ",".join("?" for _ in safe_ids)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                f"DELETE FROM query_history WHERE id IN ({placeholders})",
                safe_ids,
            )

        self.send_json({"deleted": cursor.rowcount})

    def handle_dictation_characters(self):
        chars = get_history_characters()
        self.send_json({"characters": chars})

    def handle_dictation_session_get(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM dictation_session WHERE id = 1").fetchone()
            if not row:
                self.send_json({"active": False})
                return
            session = dict(row)
            results = conn.execute(
                "SELECT char_index, character, correct, wrong_attempts FROM dictation_session_result WHERE session_id = 1 ORDER BY char_index"
            ).fetchall()
            state_row = conn.execute("SELECT * FROM dictation_session_state WHERE session_id = 1").fetchone()
            state = dict(state_row) if state_row else None

            # Auto-complete if all questions answered and not in wrong-answer state
            is_retrying = state and not state["is_correct"]
            if len(results) >= session["total_count"] and not is_retrying:
                correct_count = sum(1 for r in results if r["wrong_attempts"] == 0 and r["correct"])
                wrong_chars = "".join(r["character"] for r in results if r["wrong_attempts"] > 0)
                total = session["total_count"]
                accuracy = (correct_count / total * 100) if total > 0 else 0
                conn.execute(
                    "INSERT INTO dictation_history (characters, total_count, correct_count, wrong_characters, accuracy) VALUES (?, ?, ?, ?, ?)",
                    (session["characters"], total, correct_count, wrong_chars, round(accuracy, 1))
                )
                conn.execute("DELETE FROM dictation_session_state WHERE session_id = 1")
                conn.execute("DELETE FROM dictation_session_result WHERE session_id = 1")
                conn.execute("DELETE FROM dictation_session WHERE id = 1")
                self.send_json({
                    "active": False,
                    "auto_completed": True,
                    "session": {
                        "characters": list(session["characters"]),
                        "total_count": total,
                        "results": [dict(r) for r in results],
                        "total": total,
                        "correct": correct_count,
                        "wrong_characters": list(wrong_chars),
                        "accuracy": round(accuracy, 1)
                    }
                })
                return

        self.send_json({
            "active": True,
            "session": {
                "characters": list(session["characters"]),
                "total_count": session["total_count"],
                "current_index": session["current_index"],
                "started_at": session["started_at"],
                "results": [dict(r) for r in results],
                "state": state
            }
        })

    def handle_dictation_start(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        chars = payload.get("characters", [])
        if not isinstance(chars, list):
            self.send_json({"error": "characters must be a list"}, HTTPStatus.BAD_REQUEST)
            return
        is_retry = bool(payload.get("retry", False))
        chars = [str(c) for c in chars if isinstance(c, str) and is_hanzi(c)]
        seen = set()
        unique = []
        for c in chars:
            if c not in seen:
                unique.append(c)
                seen.add(c)
        min_chars = 1 if is_retry else 2
        if len(unique) < min_chars:
            msg = "至少需要 1 个汉字" if is_retry else "至少需要 2 个不重复的汉字"
            self.send_json({"error": msg}, HTTPStatus.BAD_REQUEST)
            return
        if len(unique) > 20:
            self.send_json({"error": "最多支持 20 个汉字"}, HTTPStatus.BAD_REQUEST)
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM dictation_session_state WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session_result WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session WHERE id = 1")
            conn.execute(
                "INSERT INTO dictation_session (id, characters, total_count, current_index) VALUES (1, ?, ?, 0)",
                ("".join(unique), len(unique))
            )
        self.send_json({
            "characters": unique,
            "total_count": len(unique),
            "current_index": 0
        }, HTTPStatus.CREATED)

    def handle_dictation_answer(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        position = payload.get("position")
        character = str(payload.get("character", "")).strip()
        if not isinstance(position, int) or position < 0:
            self.send_json({"error": "Invalid position"}, HTTPStatus.BAD_REQUEST)
            return
        if not character or not is_hanzi(character):
            self.send_json({"error": "Invalid character"}, HTTPStatus.BAD_REQUEST)
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute("SELECT * FROM dictation_session WHERE id = 1").fetchone()
            if not session:
                self.send_json({"error": "No active session"}, HTTPStatus.NOT_FOUND)
                return
            if position >= session["total_count"]:
                self.send_json({"error": "Position out of range"}, HTTPStatus.BAD_REQUEST)
                return
            # Self-verify: compare against the correct answer
            correct_char = session["characters"][position]
            is_correct = (character == correct_char)
            # Look up prior wrong_attempts from state table
            state_row = conn.execute(
                "SELECT wrong_attempts FROM dictation_session_state WHERE session_id = 1 AND char_index = ?",
                (position,)
            ).fetchone()
            prior_wrong = state_row["wrong_attempts"] if state_row else 0
            # Compute new wrong_attempts: increment only on wrong answer
            if is_correct:
                new_wrong = prior_wrong
            else:
                new_wrong = prior_wrong + 1
            conn.execute(
                """INSERT OR REPLACE INTO dictation_session_result
                   (session_id, char_index, character, correct, wrong_attempts)
                   VALUES (1, ?, ?, ?, ?)""",
                (position, correct_char, 1 if is_correct else 0, new_wrong)
            )
            if is_correct:
                conn.execute(
                    "UPDATE dictation_session SET current_index = ? WHERE id = 1",
                    (position + 1,)
                )
            conn.execute(
                """INSERT OR REPLACE INTO dictation_session_state
                   (session_id, char_index, wrong_attempts, last_answer, is_correct)
                   VALUES (1, ?, ?, ?, ?)""",
                (position, new_wrong, character, 1 if is_correct else 0)
            )
        self.send_json({"ok": True, "correct": is_correct, "wrong_attempts": new_wrong})

    def handle_dictation_complete(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute("SELECT * FROM dictation_session WHERE id = 1").fetchone()
            if not session:
                self.send_json({"error": "No active session"}, HTTPStatus.NOT_FOUND)
                return
            results = conn.execute(
                "SELECT character, correct, wrong_attempts FROM dictation_session_result WHERE session_id = 1 ORDER BY char_index"
            ).fetchall()
            correct_count = sum(1 for r in results if r["wrong_attempts"] == 0 and r["correct"])
            wrong_chars = "".join(r["character"] for r in results if r["wrong_attempts"] > 0)
            total = session["total_count"]
            accuracy = (correct_count / total * 100) if total > 0 else 0
            conn.execute(
                """INSERT INTO dictation_history (characters, total_count, correct_count, wrong_characters, accuracy)
                   VALUES (?, ?, ?, ?, ?)""",
                (session["characters"], total, correct_count, wrong_chars, round(accuracy, 1))
            )
            conn.execute("DELETE FROM dictation_session_state WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session_result WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session WHERE id = 1")
        self.send_json({
            "total": total,
            "correct": correct_count,
            "wrong_characters": list(wrong_chars),
            "accuracy": round(accuracy, 1)
        })

    def handle_dictation_session_delete(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM dictation_session_state WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session_result WHERE session_id = 1")
            conn.execute("DELETE FROM dictation_session WHERE id = 1")
        self.send_json({"ok": True})

    def handle_dictation_history_list(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM dictation_history ORDER BY id DESC LIMIT 50"
            ).fetchall()
        self.send_json({"items": [dict(row) for row in rows]})

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    port = 4173
    while port < 65535:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), ChineseHelperHandler)
            break
        except OSError:
            port += 1
    else:
        print("错误：找不到可用端口")
        return
    print(f"小学语文助手已启动：http://127.0.0.1:{port}")
    print(f"SQLite 数据库：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
