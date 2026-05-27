#!/usr/bin/env python3
import json
import sqlite3
import socket
import sys
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

        # Dictation tables — drop old schema if missing columns
        old_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(dictation_items)").fetchall()
        }
        if old_cols and "order_index" not in old_cols:
            conn.execute("DROP TABLE IF EXISTS dictation_items")
        old_scols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(dictation_sessions)").fetchall()
        }
        if old_scols and "current_index" not in old_scols:
            conn.execute("DROP TABLE IF EXISTS dictation_sessions")

        # Dictation tables
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                characters TEXT NOT NULL,
                total INTEGER NOT NULL,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_chars TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                current_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                character TEXT NOT NULL,
                correct INTEGER NOT NULL DEFAULT 0,
                corrected INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                order_index INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES dictation_sessions(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dictation_items_session ON dictation_items(session_id)"
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
        if parsed.path == "/api/dictation/active":
            self.handle_dictation_active()
            return
        if parsed.path == "/api/dictation/session":
            self.handle_dictation_session_get(parsed)
            return
        if parsed.path == "/api/dictation/history":
            self.handle_dictation_history()
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

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_delete()
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

    # ---- Dictation API handlers ----

    def handle_dictation_active(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM dictation_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row:
            self.send_json(dict(row))
        else:
            self.send_json(None)

    def handle_dictation_session_get(self, parsed):
        params = parse_qs(parsed.query)
        raw_id = params.get("id", ["0"])[0]
        try:
            session_id = int(raw_id)
        except ValueError:
            self.send_json({"error": "invalid id"}, HTTPStatus.BAD_REQUEST)
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                "SELECT * FROM dictation_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not session:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            items = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id = ? ORDER BY order_index",
                (session_id,),
            ).fetchall()
        self.send_json({"session": dict(session), "items": [dict(i) for i in items]})

    def handle_dictation_session_create(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        raw = payload.get("characters", [])
        is_retry = payload.get("retry", False)

        # Filter to Chinese characters only, deduplicate preserving order
        seen = set()
        characters = []
        for entry in raw:
            if not isinstance(entry, str):
                continue
            for ch in entry:
                if is_hanzi(ch) and ch not in seen:
                    seen.add(ch)
                    characters.append(ch)

        min_count = 1 if is_retry else 2
        if len(characters) < min_count:
            self.send_json(
                {"error": f"至少需要{min_count}个汉字"}, HTTPStatus.BAD_REQUEST
            )
            return
        if len(characters) > 20:
            self.send_json(
                {"error": "最多20个汉字"}, HTTPStatus.BAD_REQUEST
            )
            return

        # Close any existing active session
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE dictation_sessions SET status = 'abandoned' WHERE status = 'active'"
            )
            cursor = conn.execute(
                "INSERT INTO dictation_sessions (characters, total) VALUES (?, ?)",
                ("".join(characters), len(characters)),
            )
            session_id = cursor.lastrowid
            for idx, ch in enumerate(characters):
                conn.execute(
                    "INSERT INTO dictation_items (session_id, character, order_index) VALUES (?, ?, ?)",
                    (session_id, ch, idx),
                )

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                "SELECT * FROM dictation_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            items = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id = ? ORDER BY order_index",
                (session_id,),
            ).fetchall()
        self.send_json(
            {"session": dict(session), "items": [dict(i) for i in items]},
            HTTPStatus.CREATED,
        )

    def handle_dictation_attempt(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        session_id = payload.get("session_id")
        character = payload.get("character", "")
        correct = 1 if payload.get("correct") else 0
        corrected = 1 if payload.get("corrected") else 0
        if not session_id or not character:
            self.send_json(
                {"error": "session_id and character required"}, HTTPStatus.BAD_REQUEST
            )
            return

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                "SELECT * FROM dictation_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not session:
                self.send_json({"error": "session not found"}, HTTPStatus.NOT_FOUND)
                return

            # Update item
            item = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id = ? AND character = ?",
                (session_id, character),
            ).fetchone()
            if not item:
                self.send_json({"error": "item not found"}, HTTPStatus.NOT_FOUND)
                return

            conn.execute(
                "UPDATE dictation_items SET correct = ?, corrected = ?, attempt_count = attempt_count + 1 WHERE id = ?",
                (correct, corrected, item["id"]),
            )

            # Recalculate session stats
            items = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id = ? ORDER BY order_index",
                (session_id,),
            ).fetchall()
            correct_count = sum(1 for i in items if i["correct"] and not i["corrected"])
            wrong_chars = "".join(
                i["character"] for i in items if i["attempt_count"] > 0 and not i["correct"]
            )
            answered = sum(1 for i in items if i["attempt_count"] > 0)
            current_index = min(answered, len(items) - 1) if answered > 0 else 0
            status = "finished" if answered == len(items) else "active"

            conn.execute(
                "UPDATE dictation_sessions SET correct_count = ?, wrong_chars = ?, current_index = ?, status = ? WHERE id = ?",
                (correct_count, wrong_chars, current_index, status, session_id),
            )

            session = conn.execute(
                "SELECT * FROM dictation_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            items = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id = ? ORDER BY order_index",
                (session_id,),
            ).fetchall()

        self.send_json({"session": dict(session), "items": [dict(i) for i in items]})

    def handle_dictation_history(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM dictation_sessions WHERE status = 'finished' ORDER BY id DESC LIMIT 50"
            ).fetchall()
        self.send_json({"items": [dict(r) for r in rows]})

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def find_available_port(start=4173, end=4199):
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def main():
    init_db()
    port = find_available_port()
    if port is None:
        print("错误：端口 4173–4199 全部被占用，无法启动服务。", file=sys.stderr)
        sys.exit(1)
    server = ThreadingHTTPServer(("127.0.0.1", port), ChineseHelperHandler)
    print(f"小学语文助手已启动：http://127.0.0.1:{port}")
    print(f"SQLite 数据库：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
