import json

import chess
import pytest

from tracker.__main__ import should_continue
from tracker import analyze, build, lichess, motifs, review
from tracker.store import Store

RAW = {
    "id": "abcd1234", "rated": True, "variant": "standard", "speed": "blitz", "createdAt": 1762000000000,
    "status": "mate", "winner": "white",
    "players": {
        "white": {"user": {"name": "PinkRoses", "id": "pinkroses"}, "rating": 1450, "ratingDiff": 6},
        "black": {"user": {"name": "Rival", "id": "rival"}, "rating": 1470, "ratingDiff": -6},
    },
    "opening": {"eco": "C50", "name": "Italian Game: Paris Defense", "ply": 6},
    "moves": "e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#",
    "clocks": [30000, 30000, 29500, 29000, 29000, 28000, 28500],
    "clock": {"initial": 300, "increment": 0},
}


class FakeEngine:
    """Scores from a fixed white-side list, with the best move from a fixed map."""

    def __init__(self, scores, bests):
        self.scores, self.bests, self.i = scores, bests, 0

    def analyse(self, board, limit, game=None):
        cp = self.scores[self.i]
        best = self.bests.get(self.i)
        self.i += 1
        score = chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE)
        pv = [board.parse_san(best)] if best else [next(iter(board.legal_moves))]
        return {"score": score, "pv": pv}


def game_record(**changes):
    game = lichess.normalize(RAW, "PinkRoses")
    game.update(changes)
    return game


def test_normalize_is_from_the_players_side():
    game = game_record()
    assert (game["color"], game["result"], game["rating"], game["opp"], game["opp_rating"]) == ("white", "win", 1450, "Rival", 1470)
    assert game["clocks"][0] == 300
    assert lichess.normalize({**RAW, "players": {"white": {"user": {"id": "a"}}, "black": {"user": {"id": "b"}}}}, "PinkRoses") is None


def test_normalize_handles_draws_black_and_computer_opponents():
    raw = {**RAW, "players": {"white": {"aiLevel": 3}, "black": RAW["players"]["white"]}}
    raw.pop("winner")
    game = lichess.normalize(raw, "pinkroses")
    assert (game["color"], game["result"], game["opp"]) == ("black", "draw", "Stockfish level 3")


def test_win_percent_and_classification_match_lichess_scale():
    assert analyze.win_percent(0) == pytest.approx(50)
    assert analyze.classify(50, 49) is None
    assert analyze.classify(50, 44) == "inaccuracy"
    assert analyze.classify(50, 39) == "mistake"
    assert analyze.classify(50, 30) == "blunder"


def test_analysis_only_counts_the_players_moves():
    game = game_record(moves="e4 e5 Nf3 d5", clocks=[300, 300, 5, 290], init=300)
    engine = FakeEngine([20, 20, 20, -500, 900], {2: "Nc3"})
    result = analyze.analyse_game(game, engine, 1000, "SF")
    assert result["opponent_moments"][0]["san"] == "d5"
    assert result["version"] == analyze.VERSION
    assert "2" in result["lines"]
    assert result["counts"]["blunder"] == 1
    moment = result["moments"][0]
    assert (moment["ply"], moment["san"], moment["best"]) == (3, "Nf3", "Nc3")
    assert "low_clock" in moment["tags"]
    assert result["evals"] == [20, 20, 20, -500, 900]


def test_analysis_for_black_flips_the_sign():
    game = game_record(color="black", moves="e4 e5 Nf3 d5", clocks=None)
    engine = FakeEngine([0, 0, 800, 0, 0], {1: "c5"})
    result = analyze.analyse_game(game, engine, 1000, "SF")
    assert result["moments"][0]["before"] == 0
    assert result["moments"][0]["after"] == -800


def test_final_mate_needs_no_engine_call():
    engine = FakeEngine([0, 0, 0, 0, 0, 0, 0], {})
    result = analyze.analyse_game(game_record(), engine, 1000, "SF")
    assert result["evals"][-1] == 1000
    assert engine.i == 7


def test_skips_variants_short_and_broken_games():
    assert analyze.analyse_game(game_record(variant="atomic"), None, 1, "SF") == {"skipped": "variant"}
    assert analyze.analyse_game(game_record(moves="e4 e5"), None, 1, "SF") == {"skipped": "too short"}
    assert "unreadable" in analyze.analyse_game(game_record(moves="e4 e5 Ke9 d5"), None, 1, "SF")["skipped"]


def test_hangs_piece_detects_a_free_capture_only():
    free = chess.Board("4k3/8/8/4n3/3P4/8/8/4K3 w - - 0 1")
    assert analyze.hangs_piece(free, chess.Move.from_uci("d4e5"))
    defended_knight = chess.Board("4k3/3p4/2p5/3n4/4P3/8/8/4K3 w - - 0 1")
    assert not analyze.hangs_piece(defended_knight, chess.Move.from_uci("e4d5"))


def analysed_game():
    game = game_record(moves="e4 e5 Nf3 d5 exd5 Qxd5", clocks=None)
    game["analysis"] = {
        "version": analyze.VERSION, "acc": 70.0, "counts": {"inaccuracy": 0, "mistake": 0, "blunder": 1},
        "phases": {"opening": 1, "middlegame": 0, "endgame": 0}, "evals": [0, 0, 0, -500, 0, 0, 0],
        "moments": [{"ply": 3, "san": "Nf3", "best": "Nc3", "cat": "blunder", "before": 20, "after": -500,
                     "phase": "opening", "tags": ["hung_piece"], "clock": None}],
        "opponent_moments": [{"ply": 4, "san": "d5", "best": "Nc6", "cat": "mistake", "before": -500, "after": 0, "punished": True}],
        "highlights": [{"ply": 5, "san": "exd5", "why": "best reply to the error"}],
        "lines": {"2": "2. Nc3 Nf6 3. Bc4"},
    }
    return game


def good_reply(**changes):
    body = {"headline": "A sharp fight decided early.",
            "sections": [{"text": "You chose 2.Nf3 when Nc3 was better, then 3.exd5 hit back.", "line": "2.Nf3 d5 3.exd5 Qxd5"}],
            "turning_point": "2.Nf3 swung the game.", "focus": "Compare candidates before moves like 2.Nf3."}
    body.update(changes)
    return json.dumps(body)


def test_prompt_has_the_annotated_game_and_engine_lines():
    text = review.build_prompt(analysed_game())
    assert "2.Nf3?? (-5.0)" in text
    assert "2...d5? (+0.0)" in text
    assert "3.exd5!" in text
    assert "Engine line instead: 2. Nc3 Nf6 3. Bc4" in text
    assert "Position before it:" in text


def test_prompt_marks_material_changes():
    assert "[material" in review.build_prompt(analysed_game())


def test_parse_accepts_good_and_fenced_json():
    game = analysed_game()
    assert review.parse_review(good_reply(), game)["sections"][0]["line"]
    assert review.parse_review("```json\n" + good_reply() + "\n```", game)["focus"]


@pytest.mark.parametrize("reply", [
    good_reply(headline="Instead of 2.Nf3, Qh5 won."),
    good_reply(focus="Work on opening principles."),
    good_reply(focus="Check 7.Nf3 next time."),
    good_reply(turning_point="The move on ply 3 mattered."),
    good_reply(turning_point="Move 16 mattered."),
    good_reply(sections=[]),
    good_reply(turning_point="You lost a queen and it was mate."),
    "not json",
])
def test_parse_rejects_invented_or_malformed_reviews(reply):
    with pytest.raises(ValueError):
        review.parse_review(reply, analysed_game())


class FakeResponse:
    def __init__(self, status, payload=None, lines=None):
        self.status_code, self.payload, self.lines = status, payload, lines or []
        self.text = json.dumps(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append(json)
        return self.responses.pop(0)

    def get(self, url, params=None, **kwargs):
        self.calls.append(params)
        return self.responses.pop(0)


def ok(cost=0.001):
    return FakeResponse(200, {"choices": [{"message": {"content": good_reply()}}], "usage": {"cost": cost}})


CONFIG = {"model": "m", "review_max_tokens": 100, "price_per_million": {"input": 0.1, "output": 0.4},
          "max_cost_usd": 1.0, "monthly_limit_usd": 1.0, "review_latest": 2, "review_workers": 1, "reasoning": "off"}


def make_store(tmp_path, count):
    store = Store(tmp_path)
    for i in range(count):
        game = analysed_game()
        game["id"], game["at"] = f"g{i}", RAW["createdAt"] + i
        store.add(game)
    return store


def far():
    return float("inf")


def test_reviews_cover_latest_games_then_every_new_game(tmp_path):
    store = make_store(tmp_path, 5)
    assert review.review_pending(store, CONFIG, "k", far(), FakeSession([ok(), ok()])) == 2
    assert "review" in store.games["g4"] and "review" in store.games["g3"] and "review" not in store.games["g2"]
    newer = analysed_game()
    newer["id"], newer["at"] = "g9", RAW["createdAt"] + 100
    store.add(newer)
    assert review.review_pending(store, CONFIG, "k", far(), FakeSession([ok()])) == 1
    assert "review" in store.games["g9"] and "review" not in store.games["g2"]


def test_chosen_speeds_are_reviewed_across_the_full_history(tmp_path):
    store = make_store(tmp_path, 3)
    store.games["g0"]["speed"] = "rapid"
    config = {**CONFIG, "review_latest": 1, "review_all_speeds": ["rapid"]}
    assert review.review_pending(store, config, "k", far(), FakeSession([ok(), ok()])) == 2
    assert "review" in store.games["g0"] and "review" in store.games["g2"] and "review" not in store.games["g1"]


def test_monthly_override_applies_only_to_its_month(tmp_path):
    store = make_store(tmp_path, 2)
    config = {**CONFIG, "review_latest": 2, "monthly_limit_usd": 0.5, "monthly_limit_overrides": {review.month_key(): 5.0}}
    assert review.review_pending(store, config, "k", far(), FakeSession([ok(0.6), ok(0.6)])) == 2


def test_runs_continue_only_with_progress_and_remaining_work(tmp_path):
    store = make_store(tmp_path, 2)
    config = {**CONFIG, "reviews_enabled": True}
    assert should_continue(store, config, "k", 1)
    assert not should_continue(store, config, "k", 0)
    assert not should_continue(store, config, None, 1)
    assert not should_continue(store, {**config, "max_cost_usd": 0}, "k", 1)
    for game in store.games.values():
        game["review"] = {"v": review.REVIEW_VERSION}
    assert not should_continue(store, config, "k", 1)
    del store.games["g0"]["analysis"]
    assert should_continue(store, config, None, 1)


def test_old_style_reviews_are_replaced(tmp_path):
    store = make_store(tmp_path, 1)
    store.games["g0"]["review"] = {"summary": "old"}
    assert review.review_pending(store, CONFIG, "k", far(), FakeSession([ok()])) == 1
    assert store.games["g0"]["review"]["v"] == review.REVIEW_VERSION


def test_reviews_pause_at_the_monthly_limit(tmp_path):
    store = make_store(tmp_path, 2)
    session = FakeSession([ok(0.6), ok(0.6)])
    assert review.review_pending(store, {**CONFIG, "monthly_limit_usd": 0.5, "review_latest": 2}, "k", far(), session) == 1
    assert store.state["spend_by_month"][review.month_key()] == pytest.approx(0.6)


def test_reviews_stop_at_the_total_limit(tmp_path):
    store = make_store(tmp_path, 3)
    assert review.review_pending(store, {**CONFIG, "review_latest": 3, "max_cost_usd": 0.5}, "k", far(), FakeSession([ok(0.6)])) == 1


def test_no_credits_stops_everything_and_saves_nothing_bad(tmp_path):
    store = make_store(tmp_path, 2)
    session = FakeSession([FakeResponse(402, {"error": "no credits"})])
    assert review.review_pending(store, CONFIG, "k", far(), session) == 0
    assert len(session.calls) == 1
    assert not any("review" in g for g in store.games.values())


def test_missing_key_skips_reviews(tmp_path):
    assert review.review_pending(make_store(tmp_path, 1), CONFIG, None, far()) == 0


def test_rejected_reply_is_sent_back_with_the_reason_and_cost_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    store = make_store(tmp_path, 1)
    bad = FakeResponse(200, {"choices": [{"message": {"content": good_reply(headline="Qh5 won.")}}], "usage": {"cost": 0.01}})
    session = FakeSession([bad, ok(0.01)])
    assert review.review_pending(store, CONFIG, "k", far(), session) == 1
    assert store.state["cost_usd"] == pytest.approx(0.02)
    assert "rejected" in session.calls[1]["messages"][-1]["content"]


def test_unsupported_reasoning_setting_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    store = make_store(tmp_path, 1)
    session = FakeSession([FakeResponse(400, {"error": "bad"}), ok()])
    assert review.review_pending(store, CONFIG, "k", far(), session) == 1


def test_game_accuracy_punishes_blunders_more_than_a_plain_average():
    clean = analyze.game_accuracy([20] * 41, True, True)
    swung = analyze.game_accuracy([20] * 21 + [-500] * 20, True, True)
    assert clean > 98
    assert swung < clean - 10
    assert analyze.game_accuracy([20] * 41, True, False) > 98


def test_refresh_accuracy_only_touches_old_analyses(tmp_path):
    store = make_store(tmp_path, 1)
    game = store.games["g0"]
    game["analysis"].pop("version")
    assert analyze.refresh_accuracy(store) == 1
    assert game["analysis"]["acc_v"] == 2
    assert analyze.refresh_accuracy(store) == 0


def test_motifs_find_real_patterns():
    board = chess.Board("4r1k1/pp4b1/2p1r2p/4np2/P1P2B2/1P5P/6P1/3RRBK1 b - - 0 27")
    kinds = {k for k, _ in motifs.move_motifs(board, board.parse_san("Nf3+"))}
    assert "discovered attack" in kinds and "discovered check" not in kinds
    pin = chess.Board("4k3/8/8/8/8/2N1Q3/8/2K4b w - - 0 1")
    assert not any(k == "pin" for k, _ in motifs.ray_motifs(pin))
    pinned = chess.Board("r3k2r/ppp1bppp/4b1q1/8/8/2NPQB2/PPP2PPP/2KR3R b kq - 2 14")
    assert any(k == "pin" and chess.E3 in s for k, s in motifs.move_motifs(pinned, pinned.parse_san("Bg5")))


def test_real_fork_is_found():
    board = chess.Board("3q3k/8/8/4N3/8/8/8/6K1 w - - 0 1")
    assert any(k == "fork" for k, _ in motifs.move_motifs(board, board.parse_san("Nf7+")))
    quiet = chess.Board("3q3k/8/8/4N3/8/8/8/6K1 w - - 0 1")
    assert not any(k == "fork" for k, _ in motifs.move_motifs(quiet, quiet.parse_san("Ng4")))


def test_review_rejects_a_pin_the_board_does_not_show():
    with pytest.raises(ValueError, match="pin"):
        review.parse_review(good_reply(turning_point="2.Nf3 pinned the rook on a1."), analysed_game())


def test_review_rejects_a_move_number_past_the_end():
    with pytest.raises(ValueError):
        review.parse_review(good_reply(turning_point="It ended on move 4."), analysed_game())


def test_fetch_resumes_with_overlap_and_ignores_duplicates(tmp_path):
    store = Store(tmp_path)
    lines = [json.dumps(RAW).encode(), json.dumps({**RAW, "id": "next0001", "createdAt": RAW["createdAt"] + 9}).encode()]
    assert lichess.fetch_new(store, "PinkRoses", far(), FakeSession([FakeResponse(200, {}, lines)])) == 2
    session = FakeSession([FakeResponse(200, {}, lines)])
    assert lichess.fetch_new(store, "PinkRoses", far(), session) == 0
    assert session.calls[0]["since"] == RAW["createdAt"] + 9 - lichess.OVERLAP_MS


def test_store_round_trip_and_quiet_save_writes_nothing(tmp_path):
    store = make_store(tmp_path, 2)
    store.save()
    files = list((tmp_path / "games").glob("*.jsonl"))
    assert len(files) == 1
    before = files[0].stat().st_mtime_ns
    reopened = Store(tmp_path)
    assert set(reopened.games) == {"g0", "g1"}
    reopened.save()
    assert files[0].stat().st_mtime_ns == before
    assert not (tmp_path / "state.json").exists() or (tmp_path / "state.json").read_text()


def test_build_writes_summary_and_month_details(tmp_path):
    store = make_store(tmp_path / "data", 2)
    out = tmp_path / "site"
    build.build(store, {"username": "PinkRoses", "goal_rating": 1500}, out)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["total"] == 2 and summary["analysed"] == 2
    assert summary["tags"]["all"]["hung_piece"] == 100.0
    assert summary["openings"][0]["name"] == "Italian Game"
    month = next((out / "months").glob("*.json"))
    assert "g0" in json.loads(month.read_text())
