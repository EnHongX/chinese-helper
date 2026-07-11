#!/usr/bin/env python3
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.database import initialize_database
from backend.repositories import DictationRepository, HistoryRepository
from backend.services import DictationService, HistoryService, NotFoundError
from backend.utils import chinese_only, is_hanzi

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "chinese_helper.sqlite3"


def init_db():
    initialize_database(DB_PATH)


def history_service():
    return HistoryService(HistoryRepository(DB_PATH))


def dictation_service():
    return DictationService(DictationRepository(DB_PATH))


def get_history_characters():
    return history_service().recent_characters()


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
        self.send_json({"items": history_service().list(raw_limit)})

    def handle_history_create(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            item = history_service().create(
                payload.get("query", ""),
                payload.get("feature", "hanzi"),
                payload.get("characters", ""),
            )
        except ValueError:
            self.send_json(
                {"error": "query and characters are required"}, HTTPStatus.BAD_REQUEST
            )
            return
        self.send_json(item, HTTPStatus.CREATED)

    def handle_history_delete(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            deleted = history_service().delete(payload.get("ids", []))
        except TypeError:
            self.send_json({"error": "ids must be a list"}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"deleted": deleted})

    def handle_dictation_characters(self):
        chars = get_history_characters()
        self.send_json({"characters": chars})

    def handle_dictation_session_get(self):
        self.send_json(dictation_service().get_session())

    def handle_dictation_start(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = dictation_service().start(
                payload.get("characters", []),
                bool(payload.get("retry", False)),
            )
        except TypeError:
            self.send_json({"error": "characters must be a list"}, HTTPStatus.BAD_REQUEST)
            return
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result, HTTPStatus.CREATED)

    def handle_dictation_answer(self):
        payload = self.read_json_body()
        if payload is None:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = dictation_service().answer(
                payload.get("position"),
                payload.get("character", ""),
            )
        except NotFoundError as error:
            self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            return
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result)

    def handle_dictation_complete(self):
        try:
            result = dictation_service().complete()
        except NotFoundError as error:
            self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            return
        self.send_json(result)

    def handle_dictation_session_delete(self):
        self.send_json(dictation_service().delete_session())

    def handle_dictation_history_list(self):
        self.send_json({"items": dictation_service().history()})

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
