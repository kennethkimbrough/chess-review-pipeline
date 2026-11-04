"""Builds practice puzzles and the summary tables shown on the site."""
import time
from collections import Counter, defaultdict

import chess

from .analyze import win_percent
from .book import book_plies

PUZZLE_LIMIT = 6000
TREE_PLIES = 14
TREE_MIN_GAMES = 3
RECENT_GAMES = 200
TAG_TEXT = {
    "hung_piece": "leaving pieces hanging",
    "missed_material": "missing chances to win a piece",
    "allowed_mate": "allowing forced mates",
    "missed_mate": "missing forced mates",
    "low_clock": "slipping when low on time",
}
PHASE_TEXT = {"opening": "opening errors", "middlegame": "middlegame errors", "endgame": "endgame errors"}
TIME_BUCKETS = ("over 50%", "25 to 50%", "10 to 25%", "under 10%")


def analysed(game):
    analysis = game.get("analysis") or {}
    return "evals" in analysis and "skipped" not in analysis


def is_standard(game):
    return game.get("variant", "standard") == "standard" and not game.get("fen")


def strip_number(token):
    return token.split(".")[-1]


def puzzles(games):
    """Positions before the player's serious errors, where a clearly better move existed."""
    found = []
    for game in sorted(games, key=lambda g: g["at"], reverse=True):
        if len(found) >= PUZZLE_LIMIT:
            break
        if game.get("bot") or not analysed(game) or not is_standard(game):
            continue
        analysis = game["analysis"]
        wanted = [
            m for m in analysis["moments"]
            if m["cat"] in ("mistake", "blunder") and m.get("best") and m["before"] >= -200
            and win_percent(m["before"]) - win_percent(m["after"]) >= 15
        ]
        if not wanted:
            continue
        book = book_plies(game)
        wanted = [m for m in wanted if m["ply"] > book]
        if not wanted:
            continue
        sans = game["moves"].split()
        board = chess.Board()
        by_ply = {m["ply"]: m for m in wanted}
        last = max(by_ply)
        for ply, san in enumerate(sans[:last], 1):
            if ply in by_ply:
                moment = by_ply[ply]
                text = analysis.get("lines", {}).get(str(ply - 1), "")
                line = [t for t in (strip_number(w) for w in text.split()) if t][:6]
                if not line or line[0] != moment["best"]:
                    line = [moment["best"]]
                found.append({
                    "id": f"{game['id']}-{ply}", "game": game["id"], "ply": ply, "fen": board.fen(),
                    "line": line, "played": san, "cat": moment["cat"], "before": moment["before"],
                    "after": moment["after"], "phase": moment["phase"],
                    "tags": [t for t in moment["tags"] if t in TAG_TEXT], "speed": game["speed"], "at": game["at"],
                    "opp": game["opp"],
                })
            board.push_san(san)
    return found[:PUZZLE_LIMIT]


def progress(games):
    """For each time control, the recent accuracy trend and where win chances were lost most."""
    grouped = defaultdict(list)
    for game in sorted(games, key=lambda g: g["at"]):
        if game.get("rated") and not game.get("bot") and analysed(game) and game["analysis"].get("acc") is not None:
            grouped[(game.get("site", "lichess"), game["speed"])].append(game)
    rows = []
    for (site, speed), members in grouped.items():
        if len(members) < 20:
            continue
        recent, earlier = members[-RECENT_GAMES:], members[-2 * RECENT_GAMES:-RECENT_GAMES]
        tags, phases = Counter(), Counter()
        for game in recent:
            for moment in game["analysis"]["moments"]:
                if moment["cat"] == "inaccuracy":
                    continue
                drop = win_percent(moment["before"]) - win_percent(moment["after"])
                phases[moment["phase"]] += drop
                for tag in moment["tags"]:
                    if tag in TAG_TEXT:
                        tags[tag] += drop
        total = sum(phases.values()) or 1
        leak = tags.most_common(1)[0] if tags else None
        phase = phases.most_common(1)[0] if phases else None
        chunk = max(1, len(recent) // 10)
        trend = [
            round(sum(g["analysis"]["acc"] for g in recent[i:i + chunk]) / len(recent[i:i + chunk]), 1)
            for i in range(0, len(recent), chunk)
        ]
        rows.append({
            "site": site, "speed": speed, "games": len(recent),
            "accuracy": round(sum(g["analysis"]["acc"] for g in recent) / len(recent), 1),
            "previous": round(sum(g["analysis"]["acc"] for g in earlier) / len(earlier), 1) if earlier else None,
            "trend": trend,
            "leak": leak[0] if leak else None, "leak_text": TAG_TEXT[leak[0]] if leak else None,
            "leak_share": round(leak[1] * 100 / total) if leak else 0,
            "phase": phase[0] if phase else None, "phase_text": PHASE_TEXT[phase[0]] if phase else None,
            "phase_share": round(phase[1] * 100 / total) if phase else 0,
        })
    return rows


def opening_tree(games):
    """Move tree per color with results, and how often the player erred on each move."""
    trees = {"white": {}, "black": {}}

    def fresh():
        return {"n": 0, "w": 0, "d": 0, "l": 0, "e": 0, "g": [], "c": {}}

    roots = {"white": fresh(), "black": fresh()}
    for game in sorted(games, key=lambda g: g["at"], reverse=True):
        if game.get("bot") or not is_standard(game) or game["result"] not in ("win", "draw", "loss"):
            continue
        moves = game.get("moves", "").split()[:TREE_PLIES]
        if len(moves) < 2:
            continue
        errors = set()
        if analysed(game):
            errors = {m["ply"] for m in game["analysis"]["moments"] if m["cat"] != "inaccuracy"}
        node = roots[game["color"]]
        key = {"win": "w", "draw": "d", "loss": "l"}[game["result"]]
        for depth in range(len(moves) + 1):
            node["n"] += 1
            node[key] += 1
            if len(node["g"]) < 3:
                node["g"].append(game["id"])
            if depth == len(moves):
                break
            child = node["c"].setdefault(moves[depth], fresh())
            if depth + 1 in errors:
                child["e"] += 1
            node = child

    def prune(node):
        kept = {move: prune(child) for move, child in node["c"].items() if child["n"] >= TREE_MIN_GAMES}
        return {"n": node["n"], "w": node["w"], "d": node["d"], "l": node["l"], "e": node["e"], "g": node["g"], "c": kept}

    trees = {color: prune(root) for color, root in roots.items()}
    return trees


def clock_stats(games):
    """Mistake and blunder rate by how much of the clock was left, for each time control."""
    moves = defaultdict(Counter)
    errors = defaultdict(Counter)
    for game in games:
        clocks = game.get("clocks")
        initial = game.get("init")
        if game.get("bot") or not clocks or not initial or not analysed(game):
            continue
        offset = 0 if game["color"] == "white" else 1
        serious = {m["ply"] for m in game["analysis"]["moments"] if m["cat"] != "inaccuracy"}
        for index in range(offset, len(clocks), 2):
            left = clocks[index] / initial
            bucket = TIME_BUCKETS[0] if left > .5 else TIME_BUCKETS[1] if left > .25 else TIME_BUCKETS[2] if left > .1 else TIME_BUCKETS[3]
            moves[game["speed"]][bucket] += 1
            if index + 1 in serious:
                errors[game["speed"]][bucket] += 1
    rows = []
    for speed, counts in moves.items():
        if sum(counts.values()) < 200:
            continue
        rows.append({"speed": speed, "buckets": [
            {"label": b, "moves": counts[b], "rate": round(errors[speed][b] * 100 / counts[b], 1) if counts[b] else None}
            for b in TIME_BUCKETS
        ]})
    return rows


def comeback(game):
    """True for a win after being clearly lost at some point."""
    if game["result"] != "win" or not analysed(game):
        return False
    sign = 1 if game["color"] == "white" else -1
    return min(cp * sign for cp in game["analysis"]["evals"]) <= -300


def recent_tags(games, days=30):
    """Error patterns per game for recent games, for the weekly summary on the site."""
    if not games:
        return {}
    start = int(time.time() * 1000) - days * 864e5
    found = {}
    for game in games:
        if game["at"] < start or game.get("bot") or not analysed(game):
            continue
        tags = [t for m in game["analysis"]["moments"] if m["cat"] != "inaccuracy" for t in m["tags"] if t in TAG_TEXT]
        if tags:
            found[game["id"]] = tags
    return found
