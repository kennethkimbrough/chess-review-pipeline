import json

import chess
import pytest

from tracker.__main__ import should_continue
from tracker import analyze, book, build, champions, chesscom, lichess, motifs, review
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
        "version": analyze.VERSION, "great_v": analyze.GREAT_VERSION, "great": [], "acc": 70.0, "counts": {"inaccuracy": 0, "mistake": 0, "blunder": 1},
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


CC_PGN = """[Event "Live Chess"]
[Site "Chess.com"]
[White "Qqisking"]
[Black "Nelson-BOT"]
[Result "1-0"]
[ECO "C50"]
[ECOUrl "https://www.chess.com/openings/Italian-Game-Paris-Defense-3...Nc6"]
[TimeControl "600"]

1. e4 {[%clk 0:09:59.9]} 1... e5 {[%clk 0:09:58]} 2. Bc4 {[%clk 0:09:55]} 2... Nc6 {[%clk 0:09:50]} 3. Qh5 {[%clk 0:09:50]} 3... Nf6 {[%clk 0:09:40]} 4. Qxf7# {[%clk 0:09:45]} 1-0
"""
CC_CONFIG = {"chesscom_username": "Qqisking", "review_latest": 1, "monthly_limit_usd": 1, "max_cost_usd": 1}


def cc_raw(**changes):
    raw = {"url": "https://www.chess.com/game/live/123456", "pgn": CC_PGN, "time_control": "600", "end_time": 1762000000,
           "rated": False, "time_class": "rapid", "rules": "chess",
           "white": {"username": "Qqisking", "rating": 1200, "result": "win"},
           "black": {"username": "Nelson-BOT", "rating": 1300, "result": "checkmated"}}
    raw.update(changes)
    return raw


def test_chesscom_game_is_normalized_from_the_players_side():
    game = chesscom.normalize(cc_raw(), CC_CONFIG)
    assert (game["id"], game["site"], game["color"], game["result"], game["status"]) == ("cc123456", "chesscom", "white", "win", "checkmated")
    assert game["moves"] == "e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#"
    assert game["clocks"][0] == 600
    assert game["bot"] is True
    assert game["opening"].startswith("Italian Game")
    assert chesscom.normalize(cc_raw(white={"username": "x"}, black={"username": "y"}), CC_CONFIG) is None


def test_chesscom_bot_names_can_be_overridden():
    assert chesscom.is_bot("Komodo1", {})
    assert not chesscom.is_bot("Abbot", {})
    assert chesscom.is_bot("Abbot", {"chesscom_bots": ["abbot"]})
    assert not chesscom.is_bot("Nelson-BOT", {"chesscom_humans": ["nelson-bot"]})


def test_chesscom_reviews_cover_only_human_games_when_enabled(tmp_path):
    store = make_store(tmp_path, 1)
    human = analysed_game()
    human.update(id="cc1", site="chesscom", at=RAW["createdAt"] - 10**10, bot=False)
    robot = analysed_game()
    robot.update(id="cc2", site="chesscom", at=RAW["createdAt"] - 10**10, bot=True)
    store.add(human)
    store.add(robot)
    off = {g["id"] for g in review.in_scope(store, {**CC_CONFIG})}
    assert off == {"g0"}
    on = {g["id"] for g in review.in_scope(store, {**CC_CONFIG, "chesscom_reviews_enabled": True})}
    assert on == {"g0", "cc1"}


def test_lichess_resume_ignores_chesscom_games(tmp_path):
    store = make_store(tmp_path, 1)
    other = analysed_game()
    other.update(id="cc9", site="chesscom", at=RAW["createdAt"] + 10**9)
    store.add(other)
    assert store.newest_at("lichess") == RAW["createdAt"]


def test_sacrifice_needs_a_real_legal_loss():
    bxh7 = chess.Board("r1bq1rk1/ppp2ppp/2n1pn2/3p4/1b1P4/2NBPN2/PPP2PPP/R1BQ1RK1 w - - 0 8")
    assert motifs.is_sacrifice(bxh7, bxh7.parse_san("Bxh7+"))
    trade = chess.Board("4k3/8/8/3q4/8/8/3Q4/4K3 w - - 0 1")
    assert not motifs.is_sacrifice(trade, trade.parse_san("Qxd5"))
    mate = chess.Board("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1")
    assert not motifs.is_sacrifice(mate, mate.parse_san("Re8#"))
    safe = chess.Board("4k3/8/8/8/8/8/8/N3K3 w - - 0 1")
    assert not motifs.is_sacrifice(safe, safe.parse_san("Nb3"))


def test_old_analyses_are_queued_but_skipped_games_are_not():
    assert analyze.needs_engine({})
    assert analyze.needs_engine({"analysis": {"evals": []}})
    assert not analyze.needs_engine({"analysis": {"skipped": "variant"}})
    assert analyze.needs_engine({"analysis": {"version": analyze.VERSION}})
    assert not analyze.needs_engine({"analysis": {"version": analyze.VERSION, "great_v": analyze.GREAT_VERSION}})


class MultiEngine:
    def __init__(self, top, second):
        self.top, self.second = top, second

    def analyse(self, board, limit, multipv=None, game=None):
        move = next(iter(board.legal_moves))
        first = self.top if self.top is not None else move
        other = [m for m in board.legal_moves if m != first][0]
        pov = lambda cp: chess.engine.PovScore(chess.engine.Cp(cp), board.turn)
        return [{"pv": [first], "score": pov(100)}, {"pv": [other], "score": pov(self.second)}]


def great_game():
    game = game_record(moves="e4 e5 Nf3 Nc6", clocks=None)
    analysis = {"evals": [0, 0, 0, 0, 0], "moments": []}
    return game, analysis


def test_great_move_needs_top_choice_and_a_losing_alternative():
    game, analysis = great_game()
    e4 = chess.Move.from_uci("e2e4")
    assert analyze.find_great_moves(game, analysis, MultiEngine(e4, -300), 10) == [1]
    assert analyze.find_great_moves(game, analysis, MultiEngine(e4, 50), 10) == []
    assert analyze.find_great_moves(game, analysis, MultiEngine(chess.Move.from_uci("d2d4"), -300), 10) == []


def test_plain_recapture_is_not_a_great_move():
    game = game_record(moves="e4 d5 exd5", color="black", clocks=None)
    game["moves"] = "e4 d5 exd5 Qxd5 Nc3 Qa5"
    analysis = {"evals": [0] * 7, "moments": []}
    calls = []

    class Engine(MultiEngine):
        def analyse(self, board, limit, multipv=None, game=None):
            calls.append(board.fullmove_number)
            return super().analyse(board, limit, multipv, game)

    analyze.find_great_moves(game, analysis, Engine(None, 0), 10)
    assert calls == [1, 3]


LONG_GAME = "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O Re1 a6 a4 h6 h3 Be6 Bxe6 fxe6 Be3 Bxe3 Rxe3 Qe8".split()


def test_book_stops_at_the_first_position_outside_the_list():
    assert book.book_plies({"moves": "e4 e5 Nf3 Nc6 Bb5 Qh4"}) == 5
    assert book.book_plies({"moves": "e4 e5", "fen": "x"}) == 0


def test_style_features_are_from_the_players_side():
    white = champions.extract(LONG_GAME, chess.WHITE)
    black = champions.extract(LONG_GAME, chess.BLACK)
    assert white["open_e4"] == 1 and black["reply_e5"] == 1 and black["open_e4"] == 0
    assert set(white) == set(champions.FEATURES)
    assert champions.extract(LONG_GAME[:10], chess.WHITE) is None


def test_matcher_returns_three_shares_and_only_real_champions():
    match = champions.Matcher().match({"moves": " ".join(LONG_GAME), "color": "white", "variant": "standard"})
    names = [n for n, _ in match["top"]]
    assert len(names) == 3 and all(n in champions.Matcher().profiles for n in names)
    assert match["top"][0][1] >= match["top"][1][1]
    assert champions.Matcher().match({"moves": "e4 e5", "color": "white"}) is None
    overall = champions.Matcher().overall_match([{"style": match}, {"style": None}])
    assert overall["games"] == 1 and len(overall["top"]) == 3


def test_recent_batch_takes_the_newest_unreviewed_games_of_that_speed(tmp_path):
    store = make_store(tmp_path, 6)
    for name in ("g0", "g1", "g2", "g3"):
        store.games[name]["speed"] = "blitz"
    store.games["g4"]["speed"] = "bullet"
    config = {**CONFIG, "review_latest": 1, "review_recent_batch": {"speed": "blitz", "count": 2}}
    assert {g["id"] for g in review.in_scope(store, config)} == {"g5", "g3", "g2"}
    store.games["g3"]["review"] = {"v": review.REVIEW_VERSION}
    assert {g["id"] for g in review.in_scope(store, config)} == {"g5", "g3", "g2"}


def test_held_games_are_skipped_and_imports_apply_once(tmp_path):
    store = make_store(tmp_path, 2)
    (tmp_path / "review_holds.txt").write_text("g1\n")
    assert {g["id"] for g in review.in_scope(store, {**CONFIG, "review_latest": 2})} == {"g0"}
    review_data = {"headline": "x", "v": review.REVIEW_VERSION}
    (tmp_path / "imported_reviews.jsonl").write_text(json.dumps({"id": "g1", "review": review_data}) + "\n")
    assert review.import_reviews(store) == 1
    assert store.games["g1"]["review"]["headline"] == "x"
    assert review.import_reviews(store) == 0


def test_numbered_long_castling_is_not_read_as_short_castling():
    game = analysed_game()
    game["moves"] = "e4 e5 d4 d5 Bf4 Bf5 Nc3 Nc6 Qd2 Qd7 O-O-O O-O-O"
    game["analysis"]["evals"] = [0] * 13
    assert review.parse_review(good_reply(focus="Compare your options before 6.O-O-O, and 2.d4 too.", headline="Long castling on both sides.", turning_point="6.O-O-O set the plan.", sections=[{"text": "You played 6.O-O-O."}]), game)
    assert not review.PIECE_MOVE.findall("6.O-O-O")


def test_full_history_stops_at_its_spending_point_but_new_games_continue(tmp_path):
    store = make_store(tmp_path, 3)
    config = {**CONFIG, "review_latest": 1, "full_history_stop_at_usd": 1.0}
    assert {g["id"] for g in review.in_scope(store, config)} == {"g2", "g1", "g0"}
    store.state["cost_usd"] = 1.0
    assert {g["id"] for g in review.in_scope(store, config)} == {"g2"}


def test_full_history_stops_during_a_run_when_its_spending_point_passes(tmp_path):
    store = make_store(tmp_path, 4)
    config = {**CONFIG, "review_latest": 1, "max_cost_usd": 9.0, "monthly_limit_usd": 9.0, "full_history_stop_at_usd": 1.0}
    review.in_scope(store, config)
    done = review.review_pending(store, config, "k", far(), FakeSession([ok(0.6), ok(0.6), ok(0.6), ok(0.6)]))
    assert done == 2
    assert "review" not in store.games["g1"] and "review" not in store.games["g0"]


def test_unreviewable_games_are_left_off_the_site(tmp_path):
    store = make_store(tmp_path / "data", 4)
    store.games["g0"]["variant"] = "crazyhouse"
    store.games["g1"]["moves"] = "e4 e5"
    store.games["g2"]["review_failures"] = 6
    build.build(store, {"username": "PinkRoses", "goal_rating": 1500}, tmp_path / "site")
    summary = json.loads((tmp_path / "site" / "summary.json").read_text())
    assert [row[0] for row in summary["games"]] == ["g3"] and summary["total"] == 1


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
