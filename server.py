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
        ds_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(dictation_sessions)").fetchall()
        }
        if ds_cols and "total" not in ds_cols:
            conn.execute("DROP TABLE IF EXISTS dictation_sessions")
            conn.execute("DROP TABLE IF EXISTS dictation_items")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                characters TEXT NOT NULL,
                total INTEGER NOT NULL,
                current_index INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_chars TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                finished_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictation_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                char_index INTEGER NOT NULL,
                character TEXT NOT NULL,
                answer TEXT,
                correct INTEGER,
                corrected INTEGER NOT NULL DEFAULT 0,
                answered_at TEXT,
                FOREIGN KEY (session_id) REFERENCES dictation_sessions(id)
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
            self.handle_dictation_history(parsed)
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

    def handle_dictation_session_create(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        raw = str(payload.get("characters", ""))
        seen = set()
        chars = []
        for ch in raw:
            if is_hanzi(ch) and ch not in seen:
                seen.add(ch)
                chars.append(ch)
        is_retry = bool(payload.get("retry"))
        min_chars = 1 if is_retry else 2
        if len(chars) < min_chars:
            self.send_json({"error": "至少需要 2 个不重复的汉字"}, HTTPStatus.BAD_REQUEST)
            return
        if len(chars) > 20:
            self.send_json({"error": "最多只能听写 20 个不同的汉字，请减少后重试"}, HTTPStatus.BAD_REQUEST)
            return
        characters = "".join(chars)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "INSERT INTO dictation_sessions (characters, total, current_index) VALUES (?, ?, 0)",
                (characters, len(chars)),
            )
            sid = cursor.lastrowid
            for i, ch in enumerate(chars):
                conn.execute(
                    "INSERT INTO dictation_items (session_id, char_index, character) VALUES (?, ?, ?)",
                    (sid, i, ch),
                )
        self.send_json({"id": sid, "characters": characters, "total": len(chars)}, HTTPStatus.CREATED)

    def handle_dictation_active(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM dictation_sessions WHERE status='active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                self.send_json({"session": None})
                return
            session = dict(row)
            items = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id=? ORDER BY char_index",
                (session["id"],),
            ).fetchall()
            session["items"] = [dict(item) for item in items]
        self.send_json({"session": session})

    def handle_dictation_session_get(self, parsed):
        params = parse_qs(parsed.query)
        sid = params.get("id", [None])[0]
        if not sid:
            self.send_json({"error": "id is required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            sid = int(sid)
        except ValueError:
            self.send_json({"error": "invalid id"}, HTTPStatus.BAD_REQUEST)
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM dictation_sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                self.send_json({"error": "session not found"}, HTTPStatus.NOT_FOUND)
                return
            session = dict(row)
            items = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id=? ORDER BY char_index",
                (sid,),
            ).fetchall()
            session["items"] = [dict(item) for item in items]
        self.send_json({"session": session})

    def handle_dictation_attempt(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        sid = payload.get("session_id")
        char_index = payload.get("char_index")
        answer = str(payload.get("answer", "")).strip()
        corrected = payload.get("corrected", 0)
        if sid is None or char_index is None:
            self.send_json({"error": "session_id and char_index are required"}, HTTPStatus.BAD_REQUEST)
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute("SELECT * FROM dictation_sessions WHERE id=?", (sid,)).fetchone()
            if not session:
                self.send_json({"error": "session not found"}, HTTPStatus.NOT_FOUND)
                return
            item = conn.execute(
                "SELECT * FROM dictation_items WHERE session_id=? AND char_index=?",
                (sid, char_index),
            ).fetchone()
            if not item:
                self.send_json({"error": "item not found"}, HTTPStatus.NOT_FOUND)
                return
            is_correct = 1 if answer == item["character"] else 0
            corrected_now = 1 if corrected else 0
            if corrected_now:
                conn.execute(
                    "UPDATE dictation_items SET corrected=1 WHERE id=?",
                    (item["id"],),
                )
            else:
                conn.execute(
                    "UPDATE dictation_items SET answer=?, correct=?, answered_at=datetime('now','localtime') WHERE id=?",
                    (answer, is_correct, item["id"]),
                )
            cur = session["current_index"]
            if is_correct and not corrected_now:
                cur += 1
            elif is_correct and corrected_now:
                cur += 1
            new_status = session["status"]
            if cur >= session["total"]:
                new_status = "finished"
                conn.execute(
                    "UPDATE dictation_sessions SET current_index=?, status='finished', finished_at=datetime('now','localtime') WHERE id=?",
                    (cur, sid),
                )
            else:
                conn.execute(
                    "UPDATE dictation_sessions SET current_index=?, status=? WHERE id=?",
                    (cur, new_status, sid),
                )
            correct_count = conn.execute(
                "SELECT COUNT(*) FROM dictation_items WHERE session_id=? AND correct=1 AND corrected=0",
                (sid,),
            ).fetchone()[0]
            wrong = conn.execute(
                "SELECT character FROM dictation_items WHERE session_id=? AND correct=0 AND answer IS NOT NULL",
                (sid,),
            ).fetchall()
            wrong_chars = "".join(row["character"] for row in wrong)
            conn.execute(
                "UPDATE dictation_sessions SET correct_count=?, wrong_chars=? WHERE id=?",
                (correct_count, wrong_chars, sid),
            )
        self.send_json({
            "is_correct": is_correct,
            "correct_char": item["character"],
            "next_index": cur,
            "status": new_status,
        })

    def handle_dictation_history(self, parsed):
        params = parse_qs(parsed.query)
        raw_limit = params.get("limit", ["20"])[0]
        try:
            limit = min(max(int(raw_limit), 1), 50)
        except ValueError:
            limit = 20
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM dictation_sessions WHERE status='finished' ORDER BY id DESC LIMIT ?",
                (limit,),
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
    import socket
    init_db()
    port = 4173
    while port < 4200:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break
        port += 1
    server = ThreadingHTTPServer(("127.0.0.1", port), ChineseHelperHandler)
    print(f"小学语文助手已启动：http://127.0.0.1:{port}")
    print(f"SQLite 数据库：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
