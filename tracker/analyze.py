"""Runs Stockfish over each game and records what happened from the player's side."""
import math
import statistics
import threading
import time

import chess
import chess.engine

MATE_CP = 1000
PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
SUPPORTED = {"standard", "fromPosition", "chess960"}
MIN_PLIES = 4
VERSION = 2


def win_percent(cp):
    """Lichess's published mapping from centipawns to win percentage."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(win_before, win_after):
    drop = max(0.0, win_before - win_after)
    return max(0.0, min(100.0, 103.1668100711649 * math.exp(-0.04354415386753951 * drop) - 3.166924740191411 + 1))


def game_accuracy(evals, white_moves_first, is_white):
    """Lichess-style game accuracy: volatility-weighted mean averaged with the harmonic mean."""
    wins = [win_percent(cp) for cp in evals]
    moves = len(wins) - 1
    if moves < 2:
        return None
    window = max(2, min(8, moves // 10))
    windows = [wins[:window]] * (min(window, len(wins)) - 2)
    windows += [wins[i:i + window] for i in range(len(wins) - window + 1)]
    pairs = []
    for index in range(moves):
        white_to_move = (index % 2 == 0) == white_moves_first
        if white_to_move != is_white:
            continue
        before, after = wins[index], wins[index + 1]
        if not is_white:
            before, after = 100 - before, 100 - after
        pairs.append((move_accuracy(before, after), max(0.5, min(12.0, statistics.pstdev(windows[index])))))
    if not pairs:
        return None
    weighted = sum(a * w for a, w in pairs) / sum(w for _, w in pairs)
    harmonic = len(pairs) / sum(1 / max(a, 1.0) for a, _ in pairs)
    return round((weighted + harmonic) / 2, 1)


def classify(win_before, win_after):
    """Same thresholds as Lichess: 5, 10 and 15 points of win percentage."""
    drop = win_before - win_after
    if drop >= 15:
        return "blunder"
    if drop >= 10:
        return "mistake"
    if drop >= 5:
        return "inaccuracy"
    return None


def phase_of(board, ply):
    material = sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.piece_type != chess.PAWN)
    if material <= 13:
        return "endgame"
    return "opening" if ply <= 20 else "middlegame"


def score_cp(score):
    """White-side centipawns, with mates pinned to the scale's ends."""
    return max(-MATE_CP, min(MATE_CP, score.white().score(mate_score=MATE_CP * 10)))


def hangs_piece(board_after, reply):
    """True when the opponent's best reply wins a piece that can't be profitably retaken."""
    if reply is None or not board_after.is_capture(reply) or board_after.is_en_passant(reply):
        return False
    target = board_after.piece_at(reply.to_square)
    attacker = board_after.piece_at(reply.from_square)
    if target is None or PIECE_VALUE[target.piece_type] < 3:
        return False
    next_board = board_after.copy(stack=False)
    next_board.push(reply)
    defended = next_board.is_attacked_by(next_board.turn, reply.to_square)
    return not defended or PIECE_VALUE[attacker.piece_type] > PIECE_VALUE[target.piece_type]


def is_investment(board, move):
    """True when the move leaves a piece where something cheaper can take it."""
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    gained = PIECE_VALUE[captured.piece_type] if captured else 0
    after = board.copy(stack=False)
    after.push(move)
    attackers = [after.piece_at(s) for s in after.attackers(after.turn, move.to_square)]
    return bool(attackers) and piece.piece_type != chess.PAWN and (
        min(PIECE_VALUE[a.piece_type] or 99 for a in attackers) < PIECE_VALUE[piece.piece_type] - gained
    )


def refresh_accuracy(store):
    """Recalculates accuracy from stored evaluations for games analysed earlier."""
    changed = 0
    for game in list(store.games.values()):
        analysis = game.get("analysis") or {}
        if "evals" not in analysis or "acc_v" in analysis or analysis.get("version") == VERSION:
            continue
        start = chess.Board(game.get("fen") or chess.STARTING_FEN, chess960=game.get("variant") == "chess960")
        analysis["acc"] = game_accuracy(analysis["evals"], start.turn == chess.WHITE, game["color"] == "white")
        analysis["acc_v"] = 2
        store.update(game["id"], analysis=analysis)
        changed += 1
    return changed


def analyse_game(game, engine, nodes, engine_name):
    """Returns the analysis dict for a stored game, or a dict with `skipped`."""
    if game.get("variant", "standard") not in SUPPORTED:
        return {"skipped": "variant"}
    sans = game.get("moves", "").split()
    if len(sans) < MIN_PLIES:
        return {"skipped": "too short"}
    chess960 = game["variant"] == "chess960"
    start = game.get("fen") or chess.STARTING_FEN
    try:
        board = chess.Board(start, chess960=chess960)
        positions, played = [board.copy(stack=False)], []
        for san in sans:
            move = board.parse_san(san)
            played.append(move)
            board.push(move)
            positions.append(board.copy(stack=False))
    except ValueError as error:
        return {"skipped": f"unreadable moves: {error}"}

    session = object()
    evals, bests, mates, lines = [], [], [], []
    for position in positions:
        outcome = position.outcome()
        if outcome is not None:
            if outcome.winner is None:
                evals.append(0)
            else:
                evals.append(MATE_CP if outcome.winner == chess.WHITE else -MATE_CP)
            bests.append(None)
            mates.append(None)
            lines.append([])
            continue
        info = engine.analyse(position, chess.engine.Limit(nodes=nodes), game=session)
        evals.append(score_cp(info["score"]))
        pv = info.get("pv") or [None]
        bests.append(pv[0])
        lines.append(pv[:6] if pv[0] else [])
        mates.append(info["score"].pov(position.turn).mate())

    my_turn = chess.WHITE if game["color"] == "white" else chess.BLACK
    sign = 1 if my_turn == chess.WHITE else -1
    clocks = game.get("clocks") or []
    initial = game.get("init") or 0
    low_clock = max(10, initial * 0.1)
    losses = []
    opponent_moments, highlights, key_positions = [], [], set()
    counts = {"inaccuracy": 0, "mistake": 0, "blunder": 0}
    moments = []
    phases = {"opening": 0, "middlegame": 0, "endgame": 0}

    for index, move in enumerate(played):
        before_board = positions[index]
        before, after = evals[index] * sign, evals[index + 1] * sign
        win_before, win_after = win_percent(before), win_percent(after)
        if before_board.turn != my_turn:
            # The opponent's error shows up as a gain from the player's side.
            category = None if move == bests[index] else classify(100 - win_before, 100 - win_after)
            if category in ("mistake", "blunder"):
                reply_found = index + 1 < len(played) and played[index + 1] == bests[index + 1]
                opponent_moments.append({
                    "ply": index + 1, "san": sans[index],
                    "best": before_board.san(bests[index]) if bests[index] else None,
                    "cat": category, "before": before, "after": after, "punished": reply_found,
                })
                key_positions.update((index, index + 1))
                if reply_found:
                    highlights.append({"ply": index + 2, "san": sans[index + 1], "why": "best reply to the error"})
            continue
        if move == bests[index] and is_investment(before_board, move) and win_after >= win_before - 2:
            highlights.append({"ply": index + 1, "san": sans[index], "why": "best move, puts a piece en prise"})
            key_positions.add(index)
        losses.append(max(0, before - after))
        category = None if move == bests[index] else classify(win_before, win_after)
        if category is None:
            continue
        counts[category] += 1
        ply = index + 1
        key_positions.update((index, index + 1))
        phase = phase_of(before_board, ply)
        tags = []
        my_mate = mates[index]
        reply_mate = mates[index + 1]
        if my_mate is not None and my_mate > 0 and not (reply_mate is not None and reply_mate < 0):
            tags.append("missed_mate")
        if reply_mate is not None and reply_mate > 0 and not (my_mate is not None and my_mate < 0):
            tags.append("allowed_mate")
        if category != "inaccuracy":
            phases[phase] += 1
            if hangs_piece(positions[index + 1], bests[index + 1]):
                tags.append("hung_piece")
            best = bests[index]
            if best is not None and before_board.is_capture(best) and not before_board.is_en_passant(best):
                target = before_board.piece_at(best.to_square)
                if target is not None and PIECE_VALUE[target.piece_type] >= 3 and "missed_mate" not in tags:
                    tags.append("missed_material")
        clock = clocks[index] if index < len(clocks) else None
        if clock is not None and initial and clock < low_clock:
            tags.append("low_clock")
        moments.append({
            "ply": ply,
            "san": sans[index],
            "best": before_board.san(bests[index]) if bests[index] else None,
            "cat": category,
            "before": before,
            "after": after,
            "phase": phase,
            "tags": tags,
            "clock": clock,
        })

    engine_lines = {}
    for index in sorted(key_positions):
        if lines[index]:
            engine_lines[str(index)] = positions[index].variation_san(lines[index])
    white_first = chess.Board(start, chess960=chess960).turn == chess.WHITE
    return {
        "version": VERSION,
        "engine": engine_name,
        "nodes": nodes,
        "acc": game_accuracy(evals, white_first, game["color"] == "white"),
        "opponent_moments": opponent_moments,
        "highlights": highlights,
        "lines": engine_lines,
        "acpl": round(sum(losses) / len(losses)) if losses else None,
        "counts": counts,
        "phases": phases,
        "evals": evals,
        "moments": moments,
    }


def needs_engine(game):
    """Unanalysed, or analysed before the fuller format, unless it was deliberately skipped."""
    analysis = game.get("analysis")
    return analysis is None or ("skipped" not in analysis and analysis.get("version") != VERSION)


def analyse_pending(store, engine_path, nodes, workers, deadline, games=None):
    """Analyses unanalysed games, newest first, until done or out of time."""
    pending = iter(games if games is not None else [g for g in store.newest_first() if needs_engine(g)])
    lock = threading.Lock()
    done = [0]
    errors = []

    def work():
        engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        try:
            engine.configure({"Threads": 1, "Hash": 64})
            name = engine.id.get("name", "Stockfish")
            while time.time() < deadline:
                with lock:
                    game = next(pending, None)
                if game is None:
                    return
                analysis = analyse_game(game, engine, nodes, name)
                store.update(game["id"], analysis=analysis)
                with lock:
                    done[0] += 1
                    if done[0] % 200 == 0:
                        store.save()
                        print(f"Analysed {done[0]} games")
        except Exception as error:
            errors.append(error)
        finally:
            try:
                engine.quit()
            except chess.engine.EngineError:
                pass

    threads = [threading.Thread(target=work) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    store.save()
    if errors:
        print(f"Engine errors this run: {errors[:3]}")
        if not done[0]:
            raise errors[0]
    return done[0]
