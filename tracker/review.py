"""Writes each game's review from the engine's findings, through OpenRouter."""
import json
import re
import threading
import time

import chess
import requests

from . import motifs
from .analyze import PIECE_VALUE, VERSION, win_percent

URL = "https://openrouter.ai/api/v1/chat/completions"
REVIEW_VERSION = 2
SAN = r"(?:O-O(?:-O)?|[KQRBN][a-h1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)[+#]?"
NUMBERED = re.compile(rf"(?<![\w.])(\d+)(\.{{1,3}})\s?({SAN})")
PIECE_MOVE = re.compile(r"(?<![A-Za-z0-9.])(?:[KQRBN][a-h1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8]|O-O(?:-O)?)(?:=[QRBN])?[+#]?")
MOVE_NUMBER = re.compile(r"\bmoves? (\d+)", re.I)
MATERIAL_CLAIM = re.compile(
    r"\b(?:los(?:e|es|t|ing)|wins?|won|winning|hang\w*|hung|drop\w*|g[ai]ve up|giving up|sacrific\w+)\b"
    r"[^.]{0,25}\b(?:piece|knight|bishop|rook|queen|exchange)\b", re.I)
MATE_CLAIM = re.compile(r"\b(?:check)?mate\b", re.I)
TAG_TEXT = {
    "missed_mate": "a forced mate was available",
    "allowed_mate": "this allowed a forced mate",
    "hung_piece": "this left a piece to be won",
    "missed_material": "the best move won a piece or more",
    "low_clock": "low on time",
}
SYSTEM = """You are a sharp, friendly chess coach reviewing a club player's game with them. Tell the story of the game, the way a good coach talks through it over the board.

How to write:
- Write to the player as "you". Say what kind of game it was, then walk through how it developed: the opening, what each side was trying to do, the plan you built, the tactics, and how it was decided.
- Give credit when it was earned and say exactly why a move worked. Be honest about errors and what they cost. Point out what the opponent missed. Don't pad with generic praise.
- Explain ideas: which piece a move activates, what it attacks, why a recapture could wait. Use the positions (FEN) to check what you say about the board. If you can't tell from the facts, leave it out.

Hard rules:
- Every move you mention must come from the game table or an engine line given to you. Never invent moves or variations.
- Write moves with their number, such as 22.g4 or 25...Qxf6. Never use the word "ply".
- Say a piece was won or lost only if the material notes in the game table show it.
- Evaluations are from the player's side, in pawns.
- Use the words pin, skewer, fork, discovered check, discovered attack and back rank only for patterns listed under board-checked tactics, and cite the move in the same sentence. A knight check that uncovers a rook is a discovered attack, not a discovered check.

Reply with JSON only:
{"headline": "one line naming the shape of the game",
 "sections": [{"text": "a short paragraph", "line": "optional key sequence, such as 22.g4 Be4 23.g5"}],
 "turning_point": "1-2 sentences on the moment that decided it",
 "focus": "one specific thing to work on, citing a move from this game"}"""


class StopReviews(Exception):
    """A problem that retrying won't fix, such as no credits or a bad key."""


def pawns(cp):
    if abs(cp) >= 1000:
        return "forced win" if cp > 0 else "forced loss"
    return f"{cp / 100:+.1f}"


def move_label(ply):
    number = (ply + 1) // 2
    return f"{number}." if ply % 2 else f"{number}..."


def replay(game):
    board = chess.Board(game.get("fen") or chess.STARTING_FEN, chess960=game.get("variant") == "chess960")
    boards = [board.copy(stack=False)]
    for san in game["moves"].split():
        board.push_san(san)
        boards.append(board.copy(stack=False))
    return boards


def material_balance(board, color):
    total = 0
    for piece in board.piece_map().values():
        total += PIECE_VALUE[piece.piece_type] * (1 if piece.color == color else -1)
    return total


def last_move_number(boards):
    return boards[-2].fullmove_number if len(boards) > 1 else boards[-1].fullmove_number


def label_at(boards, ply):
    """Move number for the move leading to this position, from the real board."""
    previous = boards[ply - 1]
    return f"{previous.fullmove_number}." if previous.turn == chess.WHITE else f"{previous.fullmove_number}..."


def select_moments(game, limit=5):
    """Largest win-chance swings first, then back into game order."""
    moments = game["analysis"]["moments"]
    serious = [m for m in moments if m["cat"] != "inaccuracy"] or moments
    ranked = sorted(serious, key=lambda m: win_percent(m["before"]) - win_percent(m["after"]), reverse=True)
    return sorted(ranked[:limit], key=lambda m: m["ply"])


def length_for(game):
    return "3 sections at most, about 120 words" if game["speed"] in ("bullet", "ultraBullet") else "3 to 5 sections, about 250 words"


def build_prompt(game):
    analysis = game["analysis"]
    opponent = f"{game['opp']} ({game['opp_rating']})" if game.get("opp_rating") else game["opp"]
    boards = replay(game)
    moves = game["moves"].split()
    my_color = chess.WHITE if game["color"] == "white" else chess.BLACK
    evals = analysis["evals"]
    sign = 1 if my_color == chess.WHITE else -1
    marks = {m["ply"]: {"inaccuracy": "?!", "mistake": "?", "blunder": "??"}[m["cat"]] for m in analysis["moments"]}
    marks.update({m["ply"]: "?" if m["cat"] == "mistake" else "??" for m in analysis.get("opponent_moments", [])})
    good = {h["ply"]: h["why"] for h in analysis.get("highlights", [])}
    table, last_material = [], 0
    for ply, san in enumerate(moves, 1):
        mark = marks.get(ply, "!" if ply in good else "")
        material = material_balance(boards[ply], my_color) - material_balance(boards[0], my_color)
        change = f" [material {material:+d}]" if material != last_material else ""
        last_material = material
        table.append(f"{label_at(boards, ply)}{san}{mark} ({pawns(evals[ply] * sign)}){change}")
    counts = analysis["counts"]
    lines = [
        f"You played {game['color']} at rating {game.get('rating') or 'unrated'} against {opponent}.",
        f"Time control: {game['speed']}. Opening: {game.get('opening') or 'unknown'}.",
        f"Result: {game['result']} by {game['status']} after {last_move_number(boards)} moves.",
        f"Your accuracy {analysis['acc']}: blunders {counts['blunder']}, mistakes {counts['mistake']}, inaccuracies {counts['inaccuracy']}.",
        f"Length: {length_for(game)}.",
        "",
        "Game (evaluation after each move, ? and ?? are errors, ! is a strong move of yours, material is from your side):",
        " ".join(table),
        "",
    ]
    engine_lines = analysis.get("lines", {})
    def facts(ply, san, kind, details, line_label="Engine line instead"):
        parts = [f"{label_at(boards, ply)}{san} {kind}.", details]
        line = engine_lines.get(str(ply - 1))
        if line:
            parts.append(f"{line_label}: {line}.")
        parts.append(f"Position before it: {boards[ply - 1].fen()}")
        return " ".join(p for p in parts if p)
    errors = select_moments(game)
    if errors:
        lines.append("Your key errors:")
    for m in errors:
        notes = "; ".join(TAG_TEXT[t] for t in m["tags"] if t in TAG_TEXT)
        lines.append("- " + facts(m["ply"], m["san"], m["cat"], f"{m['phase'].capitalize()}, {pawns(m['before'])} to {pawns(m['after'])}. {notes}"))
    if analysis.get("opponent_moments"):
        lines.append("Your opponent's errors:")
    for m in analysis.get("opponent_moments", [])[:5]:
        found = "You found the best reply." if m["punished"] else "You didn't find the best reply."
        lines.append("- " + facts(m["ply"], m["san"], m["cat"], f"{pawns(m['before'])} to {pawns(m['after'])}. {found}"))
    if analysis.get("highlights"):
        lines.append("Your strong moves:")
    seen = set()
    for h in analysis.get("highlights", []):
        if h["ply"] in seen or len(seen) == 6:
            continue
        seen.add(h["ply"])
        lines.append("- " + facts(h["ply"], h["san"], h["why"], "", "Engine line"))
    tactics = motifs.verified_tactics(game, boards)
    lines.append("Board-checked tactics:" if tactics else "Board-checked tactics: none at the key moments.")
    lines += ["- " + t for t in tactics]
    return "\n".join(lines)


def allowed_moves(game, boards):
    numbered, bare = set(), set()
    for ply, san in enumerate(game["moves"].split(), 1):
        numbered.add((label_at(boards, ply), san.rstrip("+#")))
        bare.add(san.rstrip("+#"))
    analysis = game["analysis"]
    for key, text in analysis.get("lines", {}).items():
        for number, dots, san in NUMBERED.findall(text):
            numbered.add((f"{number}{dots}", san.rstrip("+#")))
            bare.add(san.rstrip("+#"))
        # Later black replies in a line carry no number of their own.
        for san in re.findall(SAN, text):
            bare.add(san.rstrip("+#"))
    for m in analysis["moments"] + analysis.get("opponent_moments", []):
        if m.get("best"):
            bare.add(m["best"].rstrip("+#"))
            numbered.add((label_at(boards, m["ply"]), m["best"].rstrip("+#")))
    return numbered, bare


def parse_review(text, game):
    """Returns the validated review, or raises ValueError so the call is retried."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    for key in ("headline", "turning_point", "focus"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{key} is missing")
    sections = []
    for section in data.get("sections") or []:
        if not str(section.get("text", "")).strip():
            raise ValueError("a section has no text")
        item = {"text": section["text"].strip()}
        if str(section.get("line") or "").strip():
            item["line"] = section["line"].strip()
        sections.append(item)
    if not sections:
        raise ValueError("sections are missing")
    review = {"headline": data["headline"].strip(), "sections": sections[:6],
              "turning_point": data["turning_point"].strip(), "focus": data["focus"].strip()}
    written = " ".join([review["headline"], review["turning_point"], review["focus"]]
                       + [s["text"] + " " + s.get("line", "") for s in sections])
    boards = replay(game)
    numbered, bare = allowed_moves(game, boards)
    if re.search(r"\bply\b", written, re.I):
        raise ValueError('it uses the word "ply"; use move numbers')
    for number in MOVE_NUMBER.findall(written):
        if not 1 <= int(number) <= last_move_number(boards):
            raise ValueError(f"move {number} isn't in this game")
    for number, dots, san in NUMBERED.findall(written):
        dots = "..." if dots != "." else "."
        if (f"{number}{dots}", san.rstrip("+#")) not in numbered:
            raise ValueError(f"{number}{dots}{san} isn't in the game or an engine line")
    for token in PIECE_MOVE.findall(written):
        if token.rstrip("+#") not in bare:
            raise ValueError(f"{token} isn't in the game or an engine line")
    material = [material_balance(b, chess.WHITE) for b in boards]
    if MATERIAL_CLAIM.search(written) and max(material) - min(material) < 3:
        raise ValueError("it claims a piece changed hands, but the material never moved that much")
    tags = {t for m in game["analysis"]["moments"] for t in m["tags"]}
    if MATE_CLAIM.search(written) and game["status"] != "mate" and not tags & {"missed_mate", "allowed_mate"} \
            and not any("#" in line for line in game["analysis"].get("lines", {}).values()):
        raise ValueError("it mentions mate, but no mate appears in the findings")
    if game["analysis"]["moments"] and not (NUMBERED.search(review["focus"]) or MOVE_NUMBER.search(review["focus"])):
        raise ValueError("focus must cite a move from this game")
    verifier = motifs.Verifier(game, boards)
    parts = [review["headline"], review["turning_point"], review["focus"]]
    parts += [x for sec in sections for x in (sec["text"], sec.get("line", ""))]
    for sentence in (piece for part in parts for piece in re.split(r"(?<=[a-z0-9)#+!?])\.\s+", part)):
        wrong = verifier.check_sentence(sentence, NUMBERED)
        if wrong:
            raise ValueError(f"the board doesn't show the {wrong} claimed in: {sentence.strip()[:120]}")
    return review


def request_review(game, config, key, session, model=None, reasoning=None):
    """Returns (review or None, money spent, last error)."""
    prices = config["price_per_million"]
    model = model or config["model"]
    reasoning = config.get("reasoning", "off") if reasoning is None else reasoning
    body = {
        "model": model,
        "max_tokens": config["review_max_tokens"],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "usage": {"include": True},
        "reasoning": {"enabled": False} if reasoning == "off" else {"effort": reasoning},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_prompt(game)},
        ],
    }
    last_error, spent = None, 0.0
    for attempt in range(4):
        if attempt:
            time.sleep(2 ** attempt)
        try:
            response = session.post(
                URL, json=body, timeout=180,
                headers={"Authorization": f"Bearer {key}", "X-Title": "pinkroses-lichess"},
            )
        except requests.RequestException as error:
            last_error = error
            continue
        if response.status_code in (401, 402, 403):
            raise StopReviews(f"OpenRouter returned {response.status_code}: {response.text[:200]}")
        if response.status_code == 400:
            if "reasoning" in body:
                body.pop("reasoning")
                continue
            raise StopReviews(f"OpenRouter rejected the request: {response.text[:300]}")
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            time.sleep(10)
            continue
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            last_error = payload["error"]
            continue
        usage = payload.get("usage") or {}
        cost = usage.get("cost")
        if cost is None:
            cost = (usage.get("prompt_tokens", 0) * prices["input"]
                    + usage.get("completion_tokens", 0) * prices["output"]) / 1_000_000
        spent += cost
        try:
            content = payload["choices"][0]["message"]["content"]
            review = parse_review(content, game)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            last_error = error
            if isinstance(content if "content" in locals() else None, str):
                body["messages"] = body["messages"][:2] + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That was rejected: {error}. Reply again with corrected JSON only."},
                ]
            continue
        review.update(model=model, v=REVIEW_VERSION, cost=round(spent, 6), at=int(time.time() * 1000))
        return review, spent, None
    return None, spent, last_error


def in_scope(store, config):
    """Games from the latest N onward. The starting point is fixed the first time this runs."""
    games = [g for g in store.newest_first() if len(g.get("moves", "").split()) >= 4
             and g.get("variant", "standard") in ("standard", "fromPosition", "chess960")]
    if "review_from_at" not in store.state and games:
        index = min(config["review_latest"], len(games)) - 1
        store.state["review_from_at"] = games[index]["at"]
        store.state_changed = True
    start = store.state.get("review_from_at", float("inf"))
    speeds = set(config.get("review_all_speeds", []))
    return [g for g in games if g["at"] >= start or g["speed"] in speeds]


def needs_review(game):
    return (game.get("review") or {}).get("v") != REVIEW_VERSION and game.get("review_failures", 0) < 3


def needs_analysis(game):
    return (game.get("analysis") or {}).get("version") != VERSION


def month_key():
    return time.strftime("%Y-%m", time.gmtime())


def within_limits(store, config):
    if store.state["cost_usd"] >= config["max_cost_usd"]:
        return False, f"the ${config['max_cost_usd']} total limit"
    monthly = config.get("monthly_limit_overrides", {}).get(month_key(), config["monthly_limit_usd"])
    if store.state.get("spend_by_month", {}).get(month_key(), 0) >= monthly:
        return False, f"the ${monthly} monthly limit"
    return True, ""


def review_pending(store, config, key, deadline, session=None):
    """Reviews in-scope games, newest first, within the spending limits."""
    if not key:
        print("OPENROUTER_API_KEY is not set, so reviews were skipped.")
        return 0
    session = session or requests.Session()
    pending = iter([g for g in in_scope(store, config)
                    if needs_review(g) and g.get("analysis", {}).get("version") == VERSION])
    lock = threading.Lock()
    done = [0]
    stop = threading.Event()

    def work():
        while time.time() < deadline and not stop.is_set():
            with lock:
                allowed, reason = within_limits(store, config)
                if not allowed:
                    print(f"Reviews paused at {reason}.")
                    return
                game = next(pending, None)
            if game is None:
                return
            try:
                review, spent, error = request_review(game, config, key, session)
            except StopReviews as stopped:
                print(f"Reviews stopped: {stopped}")
                stop.set()
                return
            if review is None:
                print(f"Could not review {game['id']}: {error}")
                store.update(game["id"], review_failures=game.get("review_failures", 0) + 1)
                store.add_review_cost(spent, counted=False)
                continue
            store.update(game["id"], review=review)
            store.add_review_cost(spent)
            with lock:
                done[0] += 1

    threads = [threading.Thread(target=work) for _ in range(config.get("review_workers", 4))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    store.save()
    return done[0]


def pick_test_games(store, count):
    """A mix of the newest games with something to talk about, leaning toward slower ones."""
    games = [g for g in store.newest_first() if g.get("variant") == "standard" and len(g["moves"].split()) >= 30]
    picks = []
    for speed, wanted in (("rapid", 1), ("blitz", 2), ("bullet", 2)):
        picks += [g for g in games if g["speed"] == speed][:wanted]
    for game in games:
        if len(picks) >= count:
            break
        if game not in picks:
            picks.append(game)
    return picks[:count]


def run_test(store, config, key, session=None):
    """Reviews a few games at each setting and returns the results, leaving live reviews alone."""
    session = session or requests.Session()
    output = {"model": config["model"], "settings": config["test_settings"], "games": [], "stopped": None}
    for game in pick_test_games(store, config["test_games"]):
        entry = {"id": game["id"], "speed": game["speed"], "color": game["color"], "result": game["result"],
                 "opp": game["opp"], "opening": game.get("opening"), "acc": game["analysis"]["acc"], "reviews": {}}
        for setting in config["test_settings"]:
            try:
                review, spent, error = request_review(game, config, key, session, reasoning=setting)
            except StopReviews as stopped:
                output["stopped"] = str(stopped)
                output["games"].append(entry)
                return output
            store.add_review_cost(spent, counted=False)
            entry["reviews"][setting] = {"review": review, "spent": round(spent, 6), "error": None if review else str(error)}
        output["games"].append(entry)
    return output
