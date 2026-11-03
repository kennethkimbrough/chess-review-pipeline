"""Runs Stockfish over each game and records what happened from the player's side."""
import math
import threading
import time

import chess
import chess.engine

MATE_CP = 1000
PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
SUPPORTED = {"standard", "fromPosition", "chess960"}
MIN_PLIES = 4


def win_percent(cp):
    """Lichess's published mapping from centipawns to win percentage."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(win_before, win_after):
    drop = max(0.0, win_before - win_after)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


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
    evals, bests, mates = [], [], []
    for position in positions:
        outcome = position.outcome()
        if outcome is not None:
            if outcome.winner is None:
                evals.append(0)
            else:
                evals.append(MATE_CP if outcome.winner == chess.WHITE else -MATE_CP)
            bests.append(None)
            mates.append(None)
            continue
        info = engine.analyse(position, chess.engine.Limit(nodes=nodes), game=session)
        evals.append(score_cp(info["score"]))
        pv = info.get("pv") or [None]
        bests.append(pv[0])
        mates.append(info["score"].pov(position.turn).mate())

    my_turn = chess.WHITE if game["color"] == "white" else chess.BLACK
    sign = 1 if my_turn == chess.WHITE else -1
    clocks = game.get("clocks") or []
    initial = game.get("init") or 0
    low_clock = max(10, initial * 0.1)
    accuracy, losses = [], []
    counts = {"inaccuracy": 0, "mistake": 0, "blunder": 0}
    moments = []
    phases = {"opening": 0, "middlegame": 0, "endgame": 0}

    for index, move in enumerate(played):
        before_board = positions[index]
        if before_board.turn != my_turn:
            continue
        before, after = evals[index] * sign, evals[index + 1] * sign
        win_before, win_after = win_percent(before), win_percent(after)
        accuracy.append(move_accuracy(win_before, win_after))
        losses.append(max(0, before - after))
        category = None if move == bests[index] else classify(win_before, win_after)
        if category is None:
            continue
        counts[category] += 1
        ply = index + 1
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

    return {
        "engine": engine_name,
        "nodes": nodes,
        "acc": round(sum(accuracy) / len(accuracy), 1) if accuracy else None,
        "acpl": round(sum(losses) / len(losses)) if losses else None,
        "counts": counts,
        "phases": phases,
        "evals": evals,
        "moments": moments,
    }


def analyse_pending(store, engine_path, nodes, workers, deadline):
    """Analyses unanalysed games, newest first, until done or out of time."""
    pending = iter([g for g in store.newest_first() if "analysis" not in g])
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
