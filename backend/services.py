from .utils import chinese_only, is_hanzi


class NotFoundError(Exception):
    pass


class HistoryService:
    def __init__(self, repository):
        self.repository = repository

    def create(self, query, feature="hanzi", characters=""):
        query = str(query or "").strip()
        feature = str(feature or "hanzi").strip() or "hanzi"
        characters = chinese_only(str(characters or ""))
        if not query or not characters:
            raise ValueError("query and characters are required")
        history_id = self.repository.create(feature, query, characters)
        return {
            "id": history_id,
            "feature": feature,
            "query": query,
            "characters": characters,
        }

    def list(self, limit=12):
        try:
            safe_limit = min(max(int(limit), 1), 50)
        except (TypeError, ValueError):
            safe_limit = 12
        return self.repository.list(safe_limit)

    def delete(self, ids):
        if not isinstance(ids, list):
            raise TypeError("ids must be a list")
        safe_ids = []
        for value in ids:
            try:
                safe_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return self.repository.delete(safe_ids)

    def recent_characters(self, limit=200):
        rows = self.repository.recent_characters(limit)
        chars = []
        seen = set()
        for value in rows:
            for char in value:
                if char not in seen and is_hanzi(char):
                    chars.append(char)
                    seen.add(char)
        return chars


class DictationService:
    def __init__(self, repository):
        self.repository = repository

    def start(self, characters, retry=False):
        if not isinstance(characters, list):
            raise TypeError("characters must be a list")
        chars = [str(c) for c in characters if isinstance(c, str) and is_hanzi(c)]
        seen = set()
        unique = []
        for char in chars:
            if char not in seen:
                unique.append(char)
                seen.add(char)
        min_chars = 1 if retry else 2
        if len(unique) < min_chars:
            msg = "至少需要 1 个汉字" if retry else "至少需要 2 个不重复的汉字"
            raise ValueError(msg)
        if len(unique) > 20:
            raise ValueError("最多支持 20 个汉字")

        self.repository.create_session(unique)
        return {
            "characters": unique,
            "total_count": len(unique),
            "current_index": 0,
        }

    def answer(self, position, character):
        if not isinstance(position, int) or position < 0:
            raise ValueError("Invalid position")
        character = str(character or "").strip()
        if not character or not is_hanzi(character):
            raise ValueError("Invalid character")

        session = self.repository.get_session()
        if not session:
            raise NotFoundError("No active session")
        if position >= session["total_count"]:
            raise ValueError("Position out of range")

        correct_character = session["characters"][position]
        is_correct = character == correct_character
        state = self.repository.get_state_for_index(position)
        prior_wrong = state["wrong_attempts"] if state else 0
        wrong_attempts = prior_wrong if is_correct else prior_wrong + 1
        self.repository.save_answer(
            position,
            correct_character,
            character,
            is_correct,
            wrong_attempts,
        )
        return {"ok": True, "correct": is_correct, "wrong_attempts": wrong_attempts}

    def get_session(self):
        session = self.repository.get_session()
        if not session:
            return {"active": False}

        results = self.repository.get_results()
        state = self.repository.get_state()
        is_retrying = state and not state["is_correct"]
        if len(results) >= session["total_count"] and not is_retrying:
            summary = self._complete_session(session, results)
            summary["results"] = results
            return {
                "active": False,
                "auto_completed": True,
                "session": {
                    "characters": list(session["characters"]),
                    "total_count": summary["total"],
                    "results": results,
                    "total": summary["total"],
                    "correct": summary["correct"],
                    "wrong_characters": summary["wrong_characters"],
                    "accuracy": summary["accuracy"],
                },
            }

        return {
            "active": True,
            "session": {
                "characters": list(session["characters"]),
                "total_count": session["total_count"],
                "current_index": session["current_index"],
                "started_at": session["started_at"],
                "results": results,
                "state": state,
            },
        }

    def complete(self):
        session = self.repository.get_session()
        if not session:
            raise NotFoundError("No active session")
        results = self.repository.get_completion_results()
        return self._complete_session(session, results)

    def delete_session(self):
        self.repository.clear_session()
        return {"ok": True}

    def history(self):
        return self.repository.list_history(50)

    def _complete_session(self, session, results):
        total = session["total_count"]
        correct_count = sum(
            1 for result in results if result["wrong_attempts"] == 0 and result["correct"]
        )
        wrong_chars = "".join(
            result["character"] for result in results if result["wrong_attempts"] > 0
        )
        accuracy = round((correct_count / total * 100) if total > 0 else 0, 1)
        self.repository.add_history(
            session["characters"],
            total,
            correct_count,
            wrong_chars,
            accuracy,
        )
        self.repository.clear_session()
        return {
            "total": total,
            "correct": correct_count,
            "wrong_characters": list(wrong_chars),
            "accuracy": accuracy,
        }
