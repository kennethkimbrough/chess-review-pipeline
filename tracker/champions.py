"""Compares how a game was played with the move patterns of the undisputed world champions."""
import json
import math
from pathlib import Path

import chess

VERSION = 1
MIN_PLIES = 24
MAX_PLIES = 80
PROFILE_PATH = Path(__file__).with_name("champions.json")
FEATURES = [
    "pawn_moves", "capture_rate", "check_rate", "queen_moves", "rook_moves", "minor_moves", "king_moves",
    "flank_pawns", "space", "king_pressure", "piece_pressure", "castled_long", "opposite_castling",
    "uncastled", "queens_off_early", "material_edge", "early_queen", "open_e4", "open_d4",
    "reply_e5", "reply_c5", "reply_other_e4", "reply_d5", "reply_nf6", "game_length",
]
LABELS = {
    "pawn_moves": ("more pawn moves", "fewer pawn moves"),
    "capture_rate": ("more captures", "fewer captures"),
    "check_rate": ("more checks", "fewer checks"),
    "queen_moves": ("an active queen", "a quiet queen"),
    "rook_moves": ("active rooks", "quiet rooks"),
    "minor_moves": ("lots of knight and bishop play", "little knight and bishop play"),
    "king_moves": ("an active king", "a sheltered king"),
    "flank_pawns": ("flank pawn pushes", "few flank pawn pushes"),
    "space": ("pieces pushed far forward", "pieces held back"),
    "king_pressure": ("pressure on the enemy king", "little pressure on the enemy king"),
    "piece_pressure": ("many attacks on enemy pieces", "few attacks on enemy pieces"),
    "castled_long": ("castling queenside", "avoiding queenside castling"),
    "opposite_castling": ("opposite-side castling", "same-side castling"),
    "uncastled": ("leaving the king uncastled", "castling"),
    "queens_off_early": ("an early queen trade", "keeping queens on"),
    "material_edge": ("giving up material for play", "keeping material level"),
    "early_queen": ("developing the queen early", "keeping the queen home early"),
    "game_length": ("a long game", "a short game"),
}
VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def material(board, color):
    return sum(VALUE[p.piece_type] * (1 if p.color == color else -1) for p in board.piece_map().values())


def extract(sans, color, start_fen=None):
    """Returns the feature dictionary for one side of a game, or None when it's too short."""
    if len(sans) < MIN_PLIES:
        return None
    board = chess.Board(start_fen or chess.STARTING_FEN)
    counts = dict.fromkeys(("pawn", "capture", "check", "queen", "rook", "minor", "king", "flank"), 0)
    moves = space = king_pressure = piece_pressure = samples = 0
    castled = {chess.WHITE: None, chess.BLACK: None}
    queens_off_early = False
    worst_material = 0
    early_queen = 0
    first_moves = sans[:2]
    for index, san in enumerate(sans[:MAX_PLIES]):
        move = board.parse_san(san)
        piece = board.piece_at(move.from_square)
        mover = board.turn
        if board.is_castling(move):
            castled[mover] = "short" if board.is_kingside_castling(move) else "long"
        if mover == color:
            moves += 1
            kind = piece.piece_type
            counts["pawn"] += kind == chess.PAWN
            counts["queen"] += kind == chess.QUEEN
            counts["rook"] += kind == chess.ROOK
            counts["minor"] += kind in (chess.KNIGHT, chess.BISHOP)
            counts["king"] += kind == chess.KING
            counts["capture"] += board.is_capture(move)
            counts["check"] += board.gives_check(move)
            if kind == chess.PAWN and chess.square_file(move.from_square) in (0, 1, 6, 7):
                counts["flank"] += 1
            if kind == chess.QUEEN and index < 16:
                early_queen += 1
        board.push(move)
        if index == 23 and not board.pieces(chess.QUEEN, chess.WHITE) and not board.pieces(chess.QUEEN, chess.BLACK):
            queens_off_early = True
        worst_material = min(worst_material, material(board, color))
        if index % 4 == 3:
            samples += 1
            enemy_king = board.king(not color)
            zone = chess.SquareSet(chess.BB_KING_ATTACKS[enemy_king]) if enemy_king is not None else []
            for square, own in board.piece_map().items():
                if own.color != color or own.piece_type == chess.KING:
                    continue
                rank = chess.square_rank(square)
                space += (rank if color == chess.WHITE else 7 - rank) >= 4
                attacks = board.attacks(square)
                king_pressure += sum(1 for s in zone if s in attacks)
                piece_pressure += sum(
                    1 for s in attacks
                    if board.piece_at(s) and board.piece_at(s).color != color and board.piece_at(s).piece_type != chess.PAWN
                )
    if not moves or not samples:
        return None
    mine, theirs = castled[color], castled[not color]
    return {
        "pawn_moves": counts["pawn"] / moves, "capture_rate": counts["capture"] / moves,
        "check_rate": counts["check"] / moves, "queen_moves": counts["queen"] / moves,
        "rook_moves": counts["rook"] / moves, "minor_moves": counts["minor"] / moves,
        "king_moves": counts["king"] / moves, "flank_pawns": counts["flank"] / moves,
        "space": space / samples, "king_pressure": king_pressure / samples, "piece_pressure": piece_pressure / samples,
        "castled_long": float(mine == "long"), "opposite_castling": float(bool(mine and theirs and mine != theirs)),
        "uncastled": float(mine is None), "queens_off_early": float(queens_off_early),
        "material_edge": min(worst_material, 0) / -9, "early_queen": early_queen / 8,
        "open_e4": float(color == chess.WHITE and first_moves[0] == "e4"),
        "open_d4": float(color == chess.WHITE and first_moves[0] == "d4"),
        "reply_e5": float(color == chess.BLACK and first_moves == ["e4", "e5"]),
        "reply_c5": float(color == chess.BLACK and first_moves == ["e4", "c5"]),
        "reply_other_e4": float(color == chess.BLACK and first_moves[0] == "e4" and first_moves[1] not in ("e5", "c5")),
        "reply_d5": float(color == chess.BLACK and first_moves == ["d4", "d5"]),
        "reply_nf6": float(color == chess.BLACK and first_moves == ["d4", "Nf6"]),
        "game_length": min(len(sans), 120) / 120,
    }


def fit(rows):
    """Mean and spread per feature, floored so a rarely used feature can't dominate."""
    profile = {}
    for name in FEATURES:
        values = [row[name] for row in rows]
        mean = sum(values) / len(values)
        spread = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        profile[name] = [round(mean, 4), round(max(spread, 0.04), 4)]
    return profile


def rank(features, data):
    """Scores each champion with a trained linear model, returned as shares that sum to one."""
    overall = data["overall"]
    values = [(features[n] - overall[n][0]) / overall[n][1] for n in FEATURES]
    scores = {name: model["bias"] + sum(w * v for w, v in zip(model["weights"], values))
              for name, model in data["models"].items()}
    best = max(scores.values())
    raw = {name: math.exp(score - best) for name, score in scores.items()}
    total = sum(raw.values())
    return sorted(((name, r / total) for name, r in raw.items()), key=lambda item: -item[1])


def reasons(features, champion, overall, limit=3):
    """Traits where the game and the champion both differ from the champions' average, in the same direction."""
    found = []
    for name, labels in LABELS.items():
        mean, spread = overall[name]
        game = (features[name] - mean) / spread
        theirs = (champion[name][0] - mean) / spread
        if game * theirs > 0:
            found.append((min(abs(game), 2.5) * abs(theirs), labels[0 if game > 0 else 1]))
    found.sort(reverse=True)
    return [label for score, label in found[:limit] if score > 0]


class Matcher:
    def __init__(self, path=PROFILE_PATH):
        self.data = json.loads(Path(path).read_text())
        self.profiles = self.data["champions"]
        self.overall = self.data["overall"]

    def match(self, game):
        if game.get("variant", "standard") != "standard" or game.get("fen"):
            return None
        try:
            features = extract(game.get("moves", "").split(), chess.WHITE if game["color"] == "white" else chess.BLACK)
        except ValueError:
            return None
        if features is None:
            return None
        ranked = rank(features, self.data)
        top = ranked[0][0]
        return {"top": [[name, round(share, 3)] for name, share in ranked[:3]],
                "why": reasons(features, self.profiles[top], self.overall)}


def assign(store):
    """Fills in matches for games that don't have the current version. Returns how many changed."""
    matcher = Matcher()
    changed = 0
    for game in list(store.games.values()):
        if game.get("style_v") == VERSION:
            continue
        store.update(game["id"], style=matcher.match(game), style_v=VERSION)
        changed += 1
    return changed
