"""Downloads finished games from the public Chess.com API."""
import io
import re
import time

import chess
import chess.pgn
import requests

API = "https://api.chess.com/pub/player/{user}/games/archives"
HEADERS = {"User-Agent": "chess-review-pipeline", "Accept": "application/json"}
BOT_NAME = re.compile(r"(-bot$|^bot[-_]|^komodo\d*$|^stockfish\d*$|^computer\d*$|^chesscomcomputer)", re.I)
VARIANTS = {"chess": "standard", "chess960": "chess960", "kingofthehill": "kingOfTheHill", "threecheck": "threeCheck",
            "crazyhouse": "crazyhouse", "bughouse": "bughouse"}
SPEEDS = {"daily": "correspondence"}


def is_bot(name, config):
    lowered = name.lower()
    if lowered in {n.lower() for n in config.get("chesscom_humans", [])}:
        return False
    return lowered in {n.lower() for n in config.get("chesscom_bots", [])} or bool(BOT_NAME.search(name))


def opening_name(headers):
    url = headers.get("ECOUrl", "")
    slug = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
    if not slug:
        return None
    slug = re.sub(r"-\d+\.+.*$", "", slug)
    words = slug.replace("-", " ")
    for marker in (" Defense ", " Game ", " Opening ", " Gambit ", " Attack "):
        if marker in words:
            head, tail = words.split(marker, 1)
            return f"{head}{marker.rstrip()}: {tail}"
    return words


def normalize(raw, config):
    """Turns a Chess.com game into the stored record, from the player's side."""
    me = config["chesscom_username"].lower()
    white, black = raw.get("white") or {}, raw.get("black") or {}
    if str(white.get("username", "")).lower() == me:
        color, mine, theirs = "white", white, black
    elif str(black.get("username", "")).lower() == me:
        color, mine, theirs = "black", black, white
    else:
        return None
    game = chess.pgn.read_game(io.StringIO(raw.get("pgn") or ""))
    if game is None or game.errors:
        return None
    board = game.board()
    moves, clocks = [], []
    for node in game.mainline():
        moves.append(board.san(node.move))
        board.push(node.move)
        clock = node.clock()
        if clock is not None:
            clocks.append(round(clock))
    outcome = mine.get("result", "")
    if outcome == "win":
        result, status = "win", theirs.get("result", "")
    elif outcome in ("agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"):
        result, status = "draw", outcome
    else:
        result, status = "loss", outcome
    url = raw.get("url", "")
    match = re.search(r"(\d+)/?$", url)
    if not match:
        return None
    control = str(raw.get("time_control", ""))
    initial, _, increment = control.partition("+")
    end_ms = int(raw.get("end_time", 0)) * 1000
    record = {
        "id": f"cc{match.group(1)}",
        "site": "chesscom",
        "url": url,
        "at": end_ms,
        "speed": SPEEDS.get(raw.get("time_class"), raw.get("time_class", "unknown")),
        "variant": VARIANTS.get(raw.get("rules", "chess"), raw.get("rules", "standard")),
        "rated": bool(raw.get("rated")),
        "color": color,
        "rating": mine.get("rating"),
        "diff": None,
        "opp": theirs.get("username", "Unknown"),
        "opp_rating": theirs.get("rating"),
        "result": result,
        "status": status,
        "eco": game.headers.get("ECO"),
        "opening": opening_name(game.headers),
        "moves": " ".join(moves),
        "init": int(initial) if initial.isdigit() else None,
        "inc": int(increment) if increment.isdigit() else None,
        "bot": is_bot(theirs.get("username", ""), config),
    }
    if len(clocks) == len(moves) and clocks:
        record["clocks"] = clocks
    setup = raw.get("initial_setup")
    if setup and setup != chess.STARTING_FEN:
        record["fen"] = setup
    return record


def get_json(session, url):
    for _ in range(3):
        response = session.get(url, headers=HEADERS, timeout=60)
        if response.status_code == 429:
            time.sleep(60)
            continue
        response.raise_for_status()
        return response.json()
    raise requests.RequestException(f"rate limited at {url}")


def fetch_new(store, config, session=None, base=API):
    """Downloads the months from the newest stored Chess.com game onward. Returns games added."""
    username = config.get("chesscom_username")
    if not username:
        return 0
    session = session or requests.Session()
    added = 0
    try:
        archives = get_json(session, base.format(user=username.lower())).get("archives", [])
        newest = store.newest_at("chesscom")
        if newest is not None:
            start = time.strftime("%Y/%m", time.gmtime(newest / 1000))
            archives = [a for a in archives if a[-7:] >= start]
        for archive in archives:
            for raw in get_json(session, archive).get("games", []):
                record = normalize(raw, config)
                if record and store.add(record):
                    added += 1
    except (requests.RequestException, ValueError) as error:
        print(f"Chess.com download interrupted: {error}")
    return added
