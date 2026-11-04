"""Finds how long a game stayed in known opening theory."""
from pathlib import Path

import chess

_positions = None


def positions():
    global _positions
    if _positions is None:
        _positions = set()
        for line in Path(__file__).with_name("openings.txt").read_text().splitlines():
            board = chess.Board()
            for token in line.split():
                if token[0].isdigit():
                    continue
                board.push_san(token)
                _positions.add(board.epd())
    return _positions


def book_plies(game):
    """Number of opening moves from the start that reach a position in the opening list."""
    if game.get("fen") or game.get("variant", "standard") != "standard":
        return 0
    known = positions()
    board = chess.Board()
    count = 0
    for san in game.get("moves", "").split()[:40]:
        board.push_san(san)
        if board.epd() not in known:
            break
        count += 1
    return count
