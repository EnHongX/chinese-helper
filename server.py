#!/usr/bin/env python3
import json
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
            CREATE TABLE IF NOT EXISTS dictation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                characters TEXT NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                finished_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                char_index INTEGER NOT NULL,
                expected_char TEXT NOT NULL,
                user_input TEXT NOT NULL DEFAULT '',
                correct INTEGER NOT NULL DEFAULT 0,
                corrected INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES dictation_sessions(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dictation_attempts_session ON dictation_attempts(session_id, char_index)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dictation_sessions_status ON dictation_sessions(status)"
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
            return
        if parsed.path == "/api/dictation/session":
            self.handle_dictation_session_get()
            return
        if parsed.path == "/api/dictation/results":
            self.handle_dictation_results(parsed)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_create()
            return
        if parsed.path == "/api/dictation/session":
            self.handle_dictation_session_create()
            return
        if parsed.path == "/api/dictation/attempt":
            self.handle_dictation_attempt()
            return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/dictation/attempt":
            self.handle_dictation_attempt_update()
            return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_delete()
            return
        if parsed.path == "/api/dictation/session":
            self.handle_dictation_session_delete(parsed)
            return
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

    # ── Dictation handlers ──────────────────────────────────

    def handle_dictation_session_get(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                """
                SELECT id, characters, total_count, correct_count, status, created_at
                FROM dictation_sessions
                WHERE status = 'active'
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
            if not session:
                self.send_json({"session": None})
                return
            session_dict = dict(session)
            attempts = conn.execute(
                """
                SELECT id, char_index, expected_char, user_input, correct, corrected
                FROM dictation_attempts
                WHERE session_id = ?
                ORDER BY char_index
                """,
                (session_dict["id"],),
            ).fetchall()
            session_dict["attempts"] = [dict(a) for a in attempts]
        self.send_json({"session": session_dict})

    def handle_dictation_session_create(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        raw_chars = str(payload.get("characters", ""))
        characters = chinese_only(raw_chars)
        if not characters:
            self.send_json(
                {"error": "听写字不能为空"}, HTTPStatus.BAD_REQUEST
            )
            return
        seen = []
        for ch in characters:
            if ch not in seen:
                seen.append(ch)
        characters = "".join(seen)
        if len(characters) > 20:
            characters = characters[:20]
        if not characters:
            self.send_json(
                {"error": "没有识别到汉字"}, HTTPStatus.BAD_REQUEST
            )
            return

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE dictation_sessions SET status='abandoned' WHERE status='active'"
            )
            cursor = conn.execute(
                "INSERT INTO dictation_sessions (characters, total_count) VALUES (?, ?)",
                (characters, len(characters)),
            )
            session_id = cursor.lastrowid
        self.send_json(
            {
                "id": session_id,
                "characters": characters,
                "total_count": len(characters),
            },
            HTTPStatus.CREATED,
        )

    def handle_dictation_attempt(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            session_id = int(payload["session_id"])
            char_index = int(payload["char_index"])
        except (KeyError, TypeError, ValueError):
            self.send_json(
                {"error": "session_id and char_index are required"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        expected_char = chinese_only(str(payload.get("expected_char", "")))
        user_input = chinese_only(str(payload.get("user_input", "")))
        is_retry = bool(payload.get("is_retry")) or bool(payload.get("corrected"))
        first_correct = 1 if (not is_retry and payload.get("correct")) else 0
        corrected_now = 1 if payload.get("corrected") else 0

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT id, correct FROM dictation_attempts WHERE session_id=? AND char_index=?",
                (session_id, char_index),
            ).fetchone()
            if existing:
                # Retry: keep original `correct` (first-attempt result) unchanged;
                # only flip corrected=1 when this retry is right.
                conn.execute(
                    """UPDATE dictation_attempts
                       SET user_input=?, corrected=CASE WHEN ?=1 THEN 1 ELSE corrected END
                       WHERE id=?""",
                    (user_input, corrected_now, existing["id"]),
                )
            else:
                # First attempt: record correctness of this first try.
                conn.execute(
                    """INSERT INTO dictation_attempts
                       (session_id, char_index, expected_char, user_input, correct, corrected)
                       VALUES (?, ?, ?, ?, ?, 0)""",
                    (session_id, char_index, expected_char, user_input, first_correct),
                )

            # correct_count always reflects FIRST-attempt correctness only.
            right_count = conn.execute(
                "SELECT COUNT(*) FROM dictation_attempts WHERE session_id=? AND correct=1",
                (session_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE dictation_sessions SET correct_count=? WHERE id=?",
                (right_count, session_id),
            )

            total = conn.execute(
                "SELECT total_count FROM dictation_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if total:
                attempted = conn.execute(
                    "SELECT COUNT(DISTINCT char_index) FROM dictation_attempts WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
                if attempted >= total[0]:
                    conn.execute(
                        """UPDATE dictation_sessions
                           SET status='completed',
                               finished_at=datetime('now','localtime')
                           WHERE id=? AND status='active'""",
                        (session_id,),
                    )

        self.send_json({"ok": True})

    def handle_dictation_attempt_update(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            session_id = int(payload["session_id"])
            char_index = int(payload["char_index"])
        except (KeyError, TypeError, ValueError):
            self.send_json(
                {"error": "session_id and char_index are required"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        corrected = 1 if payload.get("corrected") else 0
        user_input = chinese_only(str(payload.get("user_input", "")))

        with sqlite3.connect(DB_PATH) as conn:
            # Keep first-attempt `correct` untouched; only update corrected flag
            # and the latest user_input.
            conn.execute(
                """UPDATE dictation_attempts
                   SET corrected=?, user_input=?
                   WHERE session_id=? AND char_index=?""",
                (corrected, user_input, session_id, char_index),
            )
            right_count = conn.execute(
                "SELECT COUNT(*) FROM dictation_attempts WHERE session_id=? AND correct=1",
                (session_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE dictation_sessions SET correct_count=? WHERE id=?",
                (right_count, session_id),
            )

        self.send_json({"ok": True})

    def handle_dictation_results(self, parsed):
        params = parse_qs(parsed.query)
        raw_limit = params.get("limit", ["20"])[0]
        try:
            limit = min(max(int(raw_limit), 1), 50)
        except ValueError:
            limit = 20

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            sessions = conn.execute(
                """
                SELECT id, characters, total_count, correct_count, status,
                       created_at, finished_at
                FROM dictation_sessions
                WHERE status IN ('completed', 'active')
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            result = []
            for s in sessions:
                s_dict = dict(s)
                wrong = conn.execute(
                    """SELECT expected_char FROM dictation_attempts
                       WHERE session_id=? AND correct=0
                       ORDER BY char_index""",
                    (s_dict["id"],),
                ).fetchall()
                s_dict["wrong_chars"] = [row[0] for row in wrong]
                result.append(s_dict)

        self.send_json({"items": result})

    def handle_dictation_session_delete(self, parsed):
        params = parse_qs(parsed.query)
        raw_id = params.get("id", [None])[0]
        if raw_id is None:
            self.send_json({"error": "id is required"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            session_id = int(raw_id)
        except (TypeError, ValueError):
            self.send_json({"error": "invalid id"}, HTTPStatus.BAD_REQUEST)
            return

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM dictation_attempts WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM dictation_sessions WHERE id=?", (session_id,))

        self.send_json({"deleted": 1})

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    import socket

    init_db()
    preferred_port = 4173
    port = preferred_port
    for candidate in [preferred_port] + list(range(preferred_port + 1, preferred_port + 20)):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", candidate))
            sock.close()
            port = candidate
            break
        except OSError:
            continue

    server = ThreadingHTTPServer(("127.0.0.1", port), ChineseHelperHandler)
    print(f"小学语文助手已启动：http://127.0.0.1:{port}")
    if port != preferred_port:
        print(f"（默认端口 {preferred_port} 被占用，已切换到 {port}）")
    print(f"SQLite 数据库：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
