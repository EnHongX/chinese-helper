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
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            self.handle_history_create()
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

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 4173), ChineseHelperHandler)
    print("小学语文助手已启动：http://127.0.0.1:4173")
    print(f"SQLite 数据库：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
