"""Writes each game's review from the engine's findings, through OpenRouter."""
import json
import re
import threading
import time

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"
PIECE_MOVE = re.compile(r"(?<![A-Za-z0-9])(?:[KQRBN][a-h1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8]|O-O(?:-O)?)(?:=[QRBN])?[+#]?")
TAG_TEXT = {
    "missed_mate": "a forced mate was available and missed",
    "allowed_mate": "this move allowed a forced mate",
    "hung_piece": "the move left a piece to be won",
    "missed_material": "the best move won a piece or more",
    "low_clock": "played with little time left",
}
SYSTEM = """You review a club chess player's game for them, using engine findings you are given.
Rules:
- Only state facts in the findings. Never add moves or variations that aren't listed.
- Write to the player as "you". Be direct and specific, with no praise padding.
- The evaluations are from the player's side, in pawns.
Reply with JSON only:
{"summary": "2-3 sentences on how the game went",
 "turning_point": "1-2 sentences on the moment that decided it",
 "moments": [{"ply": <ply from the findings>, "note": "1 sentence on what went wrong or what was missed"}],
 "focus": "one concrete thing to work on, based on this game"}
Include at most 3 moments. If there are no moments listed, use an empty list."""


class StopReviews(Exception):
    """A problem that retrying won't fix, such as no credits or a bad key."""


def pawns(cp):
    if abs(cp) >= 1000:
        return "winning by force" if cp > 0 else "losing by force"
    return f"{cp / 100:+.1f}"


def move_label(ply):
    number = (ply + 1) // 2
    return f"{number}." if ply % 2 else f"{number}..."


def select_moments(game, limit=6):
    """Largest swings first, then back into game order."""
    moments = game["analysis"]["moments"]
    ranked = sorted(moments, key=lambda m: m["before"] - m["after"], reverse=True)[:limit]
    return sorted(ranked, key=lambda m: m["ply"])


def build_prompt(game):
    analysis = game["analysis"]
    opponent = f"{game['opp']} ({game['opp_rating']})" if game.get("opp_rating") else game["opp"]
    moves = game["moves"].split()
    lines = [
        f"You played {game['color']} at rating {game.get('rating') or 'unrated'} against {opponent}.",
        f"Time control: {game['speed']}. Opening: {game.get('opening') or 'unknown'}.",
        f"Result: {game['result']} by {game['status']} after {(len(moves) + 1) // 2} moves.",
        f"Accuracy {analysis['acc']}. Inaccuracies {analysis['counts']['inaccuracy']}, "
        f"mistakes {analysis['counts']['mistake']}, blunders {analysis['counts']['blunder']}.",
        "Findings:" if analysis["moments"] else "Findings: no significant errors by you.",
    ]
    for moment in select_moments(game):
        parts = [
            f"ply {moment['ply']}: {move_label(moment['ply'])} {moment['san']} was {'an' if moment['cat'] == 'inaccuracy' else 'a'} {moment['cat']} "
            f"in the {moment['phase']}, going from {pawns(moment['before'])} to {pawns(moment['after'])}.",
        ]
        if moment.get("best"):
            parts.append(f"Engine preferred {moment['best']}.")
        parts += [TAG_TEXT[t].capitalize() + "." for t in moment["tags"] if t in TAG_TEXT]
        if moment.get("clock") is not None:
            parts.append(f"{moment['clock']}s left.")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def parse_review(text, game):
    """Returns the validated review, or raises ValueError so the call is retried."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    for key in ("summary", "turning_point", "focus"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"missing {key}")
    moments = {m["ply"]: m for m in game["analysis"]["moments"]}
    notes = []
    for item in data.get("moments") or []:
        if item.get("ply") not in moments or not str(item.get("note", "")).strip():
            raise ValueError(f"unknown moment {item.get('ply')}")
        notes.append({"ply": item["ply"], "note": item["note"].strip()})
    review = {
        "summary": data["summary"].strip(),
        "turning_point": data["turning_point"].strip(),
        "moments": notes[:3],
        "focus": data["focus"].strip(),
    }
    known = set(game["moves"].split()) | {m["best"] for m in moments.values() if m.get("best")}
    known_bare = {k.rstrip("+#") for k in known}
    written = " ".join([review["summary"], review["turning_point"], review["focus"]] + [n["note"] for n in notes])
    for token in PIECE_MOVE.findall(written):
        if token.rstrip("+#") not in known_bare:
            raise ValueError(f"mentions a move that isn't in the findings: {token}")
    return review


def request_review(game, config, key, session):
    prices = config["price_per_million"]
    body = {
        "model": config["model"],
        "max_tokens": config["review_max_tokens"],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "usage": {"include": True},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_prompt(game)},
        ],
    }
    last_error = None
    spent = 0.0
    for attempt in range(4):
        if attempt:
            time.sleep(2 ** attempt)
        try:
            response = session.post(
                URL, json=body, timeout=90,
                headers={"Authorization": f"Bearer {key}", "X-Title": "pinkroses-lichess"},
            )
        except requests.RequestException as error:
            last_error = error
            continue
        if response.status_code in (401, 402, 403):
            raise StopReviews(f"OpenRouter returned {response.status_code}: {response.text[:200]}")
        if response.status_code == 400:
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
            review = parse_review(payload["choices"][0]["message"]["content"], game)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            last_error = error
            continue
        review.update(model=config["model"], cost=round(spent, 6), at=int(time.time() * 1000))
        return review, spent, None
    return None, spent, last_error


def review_pending(store, config, key, deadline, session=None, url=None):
    """Reviews analysed games, newest first, within the count and spending limits."""
    if not key:
        print("OPENROUTER_API_KEY is not set, so reviews were skipped.")
        return 0
    session = session or requests.Session()
    global URL
    if url:
        URL = url
    pending = iter([
        g for g in store.newest_first()
        if g.get("analysis") and "skipped" not in g["analysis"]
        and "review" not in g and g.get("review_failures", 0) < 3
    ])
    lock = threading.Lock()
    done = [0]
    started = [0]
    stop = threading.Event()
    limit = config.get("max_reviews_total")

    def allowed():
        if store.state["cost_usd"] >= config["max_cost_usd"]:
            print(f"Stopped at the ${config['max_cost_usd']} spending limit.")
            return False
        if limit is not None and store.state["reviews_total"] + started[0] >= limit:
            return False
        return True

    def work():
        while time.time() < deadline and not stop.is_set():
            with lock:
                if not allowed():
                    return
                game = next(pending, None)
                if game is None:
                    return
                started[0] += 1
            try:
                outcome = request_review(game, config, key, session)
            except StopReviews as error:
                print(f"Reviews stopped: {error}")
                stop.set()
                with lock:
                    started[0] -= 1
                return
            if outcome[0] is None:
                print(f"Could not review {game['id']}: {outcome[2]}")
                store.update(game["id"], review_failures=game.get("review_failures", 0) + 1)
                store.add_review_cost(outcome[1], counted=False)
                with lock:
                    started[0] -= 1
                continue
            store.update(game["id"], review=outcome[0])
            store.add_review_cost(outcome[1])
            with lock:
                started[0] -= 1
                done[0] += 1
                if done[0] % 200 == 0:
                    store.save()

    threads = [threading.Thread(target=work) for _ in range(config.get("review_workers", 4))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    store.save()
    return done[0]
