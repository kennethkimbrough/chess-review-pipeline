"""Downloads finished games from the public Lichess export API."""
import json
import time

import requests

API = "https://lichess.org/api/games/user/{user}"
OVERLAP_MS = 3 * 24 * 3600 * 1000


def normalize(raw, username):
    """Turn a Lichess export row into the stored game record, from the player's side."""
    players = raw.get("players", {})
    me = username.lower()
    color = None
    for side in ("white", "black"):
        user = players.get(side, {}).get("user") or {}
        if str(user.get("id", user.get("name", ""))).lower() == me:
            color = side
    if color is None:
        return None
    other = "black" if color == "white" else "white"
    mine, theirs = players[color], players[other]
    if "aiLevel" in theirs:
        opponent = f"Stockfish level {theirs['aiLevel']}"
    else:
        opponent = (theirs.get("user") or {}).get("name", "Anonymous")
    winner = raw.get("winner")
    result = "draw" if not winner else ("win" if winner == color else "loss")
    opening = raw.get("opening") or {}
    clock = raw.get("clock") or {}
    game = {
        "id": raw["id"],
        "at": raw["createdAt"],
        "speed": raw.get("speed", "unknown"),
        "variant": raw.get("variant", "standard"),
        "rated": bool(raw.get("rated")),
        "color": color,
        "rating": mine.get("rating"),
        "diff": mine.get("ratingDiff"),
        "opp": opponent,
        "opp_rating": theirs.get("rating"),
        "result": result,
        "status": raw.get("status", ""),
        "eco": opening.get("eco"),
        "opening": opening.get("name"),
        "moves": raw.get("moves", ""),
        "init": clock.get("initial"),
        "inc": clock.get("increment"),
    }
    if raw.get("clocks"):
        game["clocks"] = [round(c / 100) for c in raw["clocks"]]
    if raw.get("initialFen"):
        game["fen"] = raw["initialFen"]
    return game


def fetch_new(store, username, deadline, session=None, base=API):
    """Stream games oldest first from just before the newest stored one.

    The order makes an interrupted download safe to resume on the next run.
    Returns the number of games added.
    """
    session = session or requests.Session()
    newest = store.newest_at()
    params = {
        "sort": "dateAsc", "moves": "true", "clocks": "true", "opening": "true",
        "evals": "false", "tags": "false", "finished": "true", "ongoing": "false",
    }
    if newest is not None:
        params["since"] = newest - OVERLAP_MS
    added = 0
    for attempt in range(3):
        try:
            with session.get(
                base.format(user=username), params=params, stream=True, timeout=120,
                headers={"Accept": "application/x-ndjson", "User-Agent": "pinkroses-lichess"},
            ) as response:
                if response.status_code == 429:
                    time.sleep(70)
                    continue
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    game = normalize(json.loads(line), username)
                    if game and store.add(game):
                        added += 1
                    if time.time() > deadline:
                        return added
            return added
        except requests.RequestException as error:
            print(f"Lichess download interrupted: {error}")
            if store.newest_at() is not None:
                params["since"] = store.newest_at() - OVERLAP_MS
            time.sleep(10)
    return added
