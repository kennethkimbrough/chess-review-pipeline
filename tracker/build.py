"""Builds the JSON files the site reads."""
import json
import shutil
from collections import Counter, defaultdict

from . import motifs
from .store import month_of

TAGS = ["hung_piece", "missed_material", "allowed_mate", "missed_mate", "low_clock"]
RECENT = 200


def family(name):
    return name.split(":")[0].strip() if name else "Unknown"


def is_analysed(game):
    return bool(game.get("analysis")) and "skipped" not in game["analysis"]


def tag_rates(games):
    count = Counter()
    for game in games:
        for moment in game["analysis"]["moments"]:
            if moment["cat"] == "inaccuracy":
                continue
            count.update(t for t in moment["tags"] if t in TAGS)
    size = len(games) or 1
    return {tag: round(count[tag] * 100 / size, 1) for tag in TAGS}


def phase_rates(games):
    count = Counter()
    for game in games:
        count.update(game["analysis"]["phases"])
    size = len(games) or 1
    return {p: round(count[p] / size, 2) for p in ("opening", "middlegame", "endgame")}


def opening_rows(games):
    rows = defaultdict(lambda: {"white": [0, 0, 0], "black": [0, 0, 0]})
    index = {"win": 0, "draw": 1, "loss": 2}
    for game in games:
        rows[family(game.get("opening"))][game["color"]][index[game["result"]]] += 1
    output = []
    for name, sides in rows.items():
        for color, record in sides.items():
            if sum(record):
                output.append({"name": name, "color": color, "win": record[0], "draw": record[1], "loss": record[2]})
    output.sort(key=lambda r: r["win"] + r["draw"] + r["loss"], reverse=True)
    return output[:30]


def build(store, config, out):
    if out.exists():
        shutil.rmtree(out)
    (out / "months").mkdir(parents=True)
    games = sorted(store.games.values(), key=lambda g: g["at"])
    rows, months = [], defaultdict(list)
    for game in games:
        analysis = game.get("analysis") or {}
        counts = analysis.get("counts") or {}
        game["sacrifices"] = motifs.sacrifices(game)
        rows.append([
            game["id"], game["at"], game["speed"], int(game["rated"]), game["color"][0],
            game.get("rating"), game.get("diff"), game["opp"], game.get("opp_rating"),
            game["result"], family(game.get("opening")), analysis.get("acc"),
            counts.get("blunder"), counts.get("mistake"), int("review" in game),
            game.get("site", "lichess"), int(bool(game.get("bot"))), len(game["sacrifices"]),
            len(game.get("moves", "").split()),
        ])
        months[month_of(game["at"])].append(game)
    for month, members in months.items():
        details = {}
        for game in members:
            analysis = game.get("analysis") or {}
            details[game["id"]] = {
                "moves": game.get("moves", ""), "fen": game.get("fen"), "status": game["status"], "url": game.get("url"), "sacrifices": game["sacrifices"],
                "opening": game.get("opening"), "eco": game.get("eco"), "variant": game.get("variant"),
                "evals": analysis.get("evals"), "moments": analysis.get("moments"),
                "acpl": analysis.get("acpl"), "counts": analysis.get("counts"),
                "engine": analysis.get("engine"), "skipped": analysis.get("skipped"),
                "review": game.get("review"),
            }
        (out / "months" / f"{month}.json").write_text(json.dumps(details, separators=(",", ":"), ensure_ascii=False))
    analysed = [g for g in games if is_analysed(g) and not g.get("bot")]
    recent = analysed[-RECENT:]
    summary = {
        "username": config["username"],
        "goal": config["goal_rating"],
        "total": len(games),
        "analysed": len(analysed),
        "reviewed": sum("review" in g for g in games),
        "cost": store.state["cost_usd"],
        "games": rows,
        "tags": {"recent": tag_rates(recent), "all": tag_rates(analysed)},
        "phases": {"recent": phase_rates(recent), "all": phase_rates(analysed)},
        "recent_size": len(recent),
        "openings": opening_rows([g for g in games if g["result"] and not g.get("bot")]),
        "chesscom_username": config.get("chesscom_username"),
    }
    (out / "summary.json").write_text(json.dumps(summary, separators=(",", ":"), ensure_ascii=False))
