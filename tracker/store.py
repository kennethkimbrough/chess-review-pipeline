"""Game storage: one JSON Lines file per month, plus a small state file."""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def month_of(at_ms):
    return datetime.fromtimestamp(at_ms / 1000, timezone.utc).strftime("%Y-%m")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.games_dir = self.root / "games"
        self.state_path = self.root / "state.json"
        self.games = {}
        self.dirty = set()
        self.lock = threading.Lock()
        self.state = {"reviews_total": 0, "cost_usd": 0.0}
        if self.state_path.exists():
            self.state.update(json.loads(self.state_path.read_text()))
        for path in sorted(self.games_dir.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                game = json.loads(line)
                self.games[game["id"]] = game

    def add(self, game):
        """Add a new game. Returns False when it is already stored."""
        with self.lock:
            if game["id"] in self.games:
                return False
            self.games[game["id"]] = game
            self.dirty.add(month_of(game["at"]))
            return True

    def update(self, game_id, **fields):
        with self.lock:
            game = self.games[game_id]
            game.update(fields)
            self.dirty.add(month_of(game["at"]))

    def add_review_cost(self, cost, counted=True):
        with self.lock:
            self.state["reviews_total"] += 1 if counted else 0
            self.state["cost_usd"] = round(self.state["cost_usd"] + cost, 6)
            month = month_of(int(time.time() * 1000))
            spend = self.state.setdefault("spend_by_month", {})
            spend[month] = round(spend.get(month, 0) + cost, 6)
            self.state_changed = True

    def newest_at(self):
        return max((g["at"] for g in self.games.values()), default=None)

    def newest_first(self):
        return sorted(self.games.values(), key=lambda g: g["at"], reverse=True)

    state_changed = False

    def save(self):
        """Write only what changed, so quiet runs leave the repo untouched."""
        with self.lock:
            if not self.dirty and not self.state_changed:
                return
            self.games_dir.mkdir(parents=True, exist_ok=True)
            by_month = {}
            for game in self.games.values():
                month = month_of(game["at"])
                if month in self.dirty:
                    by_month.setdefault(month, []).append(game)
            for month, games in by_month.items():
                games.sort(key=lambda g: (g["at"], g["id"]))
                text = "".join(json.dumps(g, separators=(",", ":"), ensure_ascii=False) + "\n" for g in games)
                tmp = self.games_dir / f"{month}.jsonl.tmp"
                tmp.write_text(text)
                tmp.replace(self.games_dir / f"{month}.jsonl")
            self.state_path.write_text(json.dumps(self.state, indent=2) + "\n")
            self.dirty.clear()
            self.state_changed = False
