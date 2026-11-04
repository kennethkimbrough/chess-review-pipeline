"""Finds tactical patterns on the board so reviews can only name ones that are really there."""
import re

import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
DIAGONAL = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
STRAIGHT = [(1, 0), (-1, 0), (0, 1), (0, -1)]
RAYS = {chess.BISHOP: DIAGONAL, chess.ROOK: STRAIGHT, chess.QUEEN: DIAGONAL + STRAIGHT}
WORDS = {
    "pin": re.compile(r"\b(?:un)?pin(?:s|ned|ning)?\b", re.I),
    "skewer": re.compile(r"\bskewer\w*\b", re.I),
    "fork": re.compile(r"\bfork\w*\b", re.I),
    "discovered check": re.compile(r"\bdiscovered check\b", re.I),
    "discovered attack": re.compile(r"\bdiscover(?:ed|y|able)\b(?! check)", re.I),
    "back rank": re.compile(r"\bback[- ]rank\b", re.I),
}
NUMBER_PREFIX = re.compile(r"^\d+\.+")
SQUARE = re.compile(r"(?<![A-Za-z0-9])[a-h][1-8](?![0-9])")


def ray_motifs(board):
    """Pins and skewers on the board, as (kind, squares involved)."""
    found = []
    for origin, slider in board.piece_map().items():
        for dx, dy in RAYS.get(slider.piece_type, []):
            hits = []
            file, rank = chess.square_file(origin) + dx, chess.square_rank(origin) + dy
            while 0 <= file < 8 and 0 <= rank < 8 and len(hits) < 2:
                square = chess.square(file, rank)
                piece = board.piece_at(square)
                if piece:
                    if piece.color == slider.color:
                        break
                    hits.append((square, piece))
                file, rank = file + dx, rank + dy
            if len(hits) < 2:
                continue
            (near, near_piece), (far, far_piece) = hits
            squares = {origin, near, far}
            if VALUE[near_piece.piece_type] < VALUE[far_piece.piece_type] and VALUE[far_piece.piece_type] >= 3:
                found.append(("pin", squares))
            elif VALUE[near_piece.piece_type] > VALUE[far_piece.piece_type] and VALUE[near_piece.piece_type] >= 5 and VALUE[far_piece.piece_type] >= 3:
                found.append(("skewer", squares))
    return found


def is_target(after, attacker_value, square, attacked_color):
    piece = after.piece_at(square)
    if piece is None or piece.color != attacked_color or piece.piece_type == chess.PAWN:
        return False
    return VALUE[piece.piece_type] > attacker_value or not after.is_attacked_by(attacked_color, square)


def move_motifs(board, move):
    """Patterns this move creates, as (kind, squares involved)."""
    mover = board.turn
    moved = board.piece_at(move.from_square)
    after = board.copy(stack=False)
    after.push(move)
    enemy = not mover
    found = []
    to = move.to_square
    if moved is None:
        return found
    if after.is_check():
        for checker in after.checkers():
            if checker != to:
                found.append(("discovered check", {checker, to, after.king(enemy)}))
    placed = after.piece_at(to)
    targets = [s for s in after.attacks(to) if is_target(after, VALUE[placed.piece_type], s, enemy)]
    if len(targets) >= 2:
        found.append(("fork", {to, *targets}))
    for origin, piece in after.piece_map().items():
        if piece.color != mover or origin == to or piece.piece_type not in RAYS:
            continue
        for square in after.attacks(origin) & after.occupied_co[enemy]:
            if square in board.attacks(origin):
                continue
            if after.piece_at(square).piece_type != chess.PAWN:
                found.append(("discovered attack", {origin, square, move.from_square, to}))
    for kind, squares in ray_motifs(after):
        if to in squares and placed.color == mover and (after.piece_at(to).piece_type in RAYS):
            pinner_side = after.piece_at(to).color == mover
            if pinner_side:
                found.append((kind, squares))
    king = after.king(enemy)
    home = 0 if enemy == chess.WHITE else 7
    if king is not None and chess.square_rank(king) == home and after.is_check():
        for checker in after.checkers():
            attacker = after.piece_at(checker)
            if attacker.piece_type in (chess.ROOK, chess.QUEEN) and chess.square_rank(checker) == home:
                found.append(("back rank", {checker, king}))
    return found


def label(board):
    return f"{board.fullmove_number}." if board.turn == chess.WHITE else f"{board.fullmove_number}..."


def describe(squares):
    return ", ".join(sorted(chess.square_name(s) for s in squares))


class Verifier:
    """Answers whether a pattern exists at cited moves, or anywhere in the game and engine lines."""

    def __init__(self, game, boards):
        self.boards = boards
        self.moves = [boards[i].parse_san(s) for i, s in enumerate(game["moves"].split())]
        self.everywhere = []
        for index, move in enumerate(self.moves):
            self.everywhere += self.at(index, move)
        self.line_positions = {}
        for key, text in game["analysis"].get("lines", {}).items():
            board = boards[int(key)].copy(stack=False)
            for token in text.split():
                token = NUMBER_PREFIX.sub("", token)
                if not token:
                    continue
                try:
                    move = board.parse_san(token)
                except ValueError:
                    break
                self.everywhere += move_motifs(board, move) + ray_motifs(board)
                self.line_positions.setdefault((label(board), token.rstrip("+#")), (board.copy(stack=False), move))
                board.push(move)

    def at(self, index, move):
        board = self.boards[index]
        after = self.boards[index + 1]
        return move_motifs(board, move) + ray_motifs(board) + ray_motifs(after)

    def cited(self, number, dots, san):
        name = f"{number}{'.' if dots == '.' else '...'}"
        bare = san.rstrip("+#")
        for index, board in enumerate(self.boards[:-1]):
            if label(board) != name:
                continue
            found = []
            try:
                move = board.parse_san(bare)
            except ValueError:
                return []
            found += move_motifs(board, move) + ray_motifs(board)
            next_board = board.copy(stack=False)
            next_board.push(move)
            found += ray_motifs(next_board)
            if index < len(self.moves) and self.moves[index] == move and index + 1 < len(self.moves):
                found += self.at(index + 1, self.moves[index + 1])
            return found
        if (name, bare) in self.line_positions:
            board, move = self.line_positions[(name, bare)]
            return move_motifs(board, move) + ray_motifs(board)
        return []

    def check_sentence(self, sentence, numbered):
        """Returns the name of a pattern the sentence claims but the board doesn't show."""
        citations = numbered.findall(sentence)
        moves_text = numbered.sub(" ", sentence)
        squares = {chess.parse_square(s) for s in SQUARE.findall(moves_text)}
        for kind, word in WORDS.items():
            if not word.search(sentence):
                continue
            pool = []
            for number, dots, san in citations:
                pool += self.cited(number, dots, san)
            if not citations:
                pool = self.everywhere
            matching = [squares_found for found_kind, squares_found in pool if found_kind == kind]
            if kind == "discovered attack":
                matching += [s for k, s in pool if k == "discovered check"]
            if not matching:
                return kind
            if squares and not any(squares & found for found in matching):
                return kind
        return None


def verified_tactics(game, boards, limit=14):
    """Board-checked patterns at the game's important moves, written for the prompt."""
    analysis = game["analysis"]
    verifier_moves = game["moves"].split()
    important = {m["ply"] for m in analysis["moments"] + analysis.get("opponent_moments", [])}
    important |= {h["ply"] for h in analysis.get("highlights", [])}
    lines = []
    for ply in sorted(important):
        board = boards[ply - 1]
        san = verifier_moves[ply - 1]
        for kind, squares in move_motifs(board, board.parse_san(san)):
            lines.append(f"{label(board)}{san} played: {kind} ({describe(squares)})")
        text = analysis.get("lines", {}).get(str(ply - 1))
        if text:
            best = next((t for t in (NUMBER_PREFIX.sub("", w) for w in text.split()) if t), None)
            if best and best != san:
                for kind, squares in move_motifs(board, board.parse_san(best)):
                    lines.append(f"{label(board)}{best} engine move: {kind} ({describe(squares)})")
    return lines[:limit]


def is_sacrifice(board, move):
    """True when a non-pawn piece can be taken at a real loss, the move isn't mate, and the capture is legal."""
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
        return False
    captured = board.piece_at(move.to_square)
    gained = VALUE[captured.piece_type] if captured else 0
    if VALUE[piece.piece_type] - gained < 2:
        return False
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return False
    takers = [after.piece_at(m.from_square) for m in after.legal_moves if m.to_square == move.to_square]
    return any(t.piece_type == chess.KING or VALUE[t.piece_type] < VALUE[piece.piece_type] for t in takers)


def sacrifices(game):
    """Plies where the player made the engine's top move and it was a real sacrifice."""
    analysis = game.get("analysis") or {}
    plies = sorted({h["ply"] for h in analysis.get("highlights", []) if "en prise" in h["why"]})
    if not plies:
        return []
    board = chess.Board(game.get("fen") or chess.STARTING_FEN, chess960=game.get("variant") == "chess960")
    found = []
    for ply, san in enumerate(game["moves"].split(), 1):
        move = board.parse_san(san)
        if ply in plies and is_sacrifice(board, move):
            found.append(ply)
        board.push(move)
    return found
