"""Command line: `python -m tracker run` updates the data, `build` makes the site data."""
import argparse
import json
import os
import time
from pathlib import Path

from . import analyze, build, champions, chesscom, lichess, review
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def should_continue(store, config, key, progress):
    """True when work remains and this run got something done, so failures can't loop."""
    if not progress:
        return False
    if any(analyze.needs_engine(g) or analyze.needs_mates(g) for g in store.games.values()):
        return True
    if not (config.get("reviews_enabled") and key and review.within_limits(store, config)[0]):
        return False
    return any(review.needs_review(g) for g in review.in_scope(store, config))


def run_review_test(store, config, key, args, path):
    picks = review.pick_test_games(store, config["test_games"])
    limit = time.time() + 600
    analyze.analyse_pending(store, args.engine, config["engine_nodes"], args.workers, limit,
                            games=[g for g in picks if review.needs_analysis(g)])
    output = review.run_test(store, config, key)
    try:
        lichess_accuracy = lichess.fetch_lichess_accuracy(config["username"])
        known = [store.games[i] for i in lichess_accuracy if i in store.games]
        analyze.analyse_pending(store, args.engine, config["engine_nodes"], args.workers, time.time() + 300,
                                games=[g for g in known if review.needs_analysis(g)])
        output["accuracy_check"] = [
            {"id": g["id"], "lichess": lichess_accuracy[g["id"]], "ours": g["analysis"].get("acc")} for g in known
        ]
    except Exception as error:
        output["accuracy_check_error"] = str(error)
    path.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n")
    store.save()


def main():
    parser = argparse.ArgumentParser(prog="tracker")
    parser.add_argument("command", choices=["run", "build"])
    parser.add_argument("--minutes", type=float, default=100, help="time limit for this run")
    parser.add_argument("--engine", default=os.environ.get("STOCKFISH_PATH", "stockfish"))
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text())
    store = Store(ROOT / "data")
    if args.command == "build":
        build.build(store, config, ROOT / "site" / "data")
        return

    start = time.time()
    deadline = start + args.minutes * 60
    added = lichess.fetch_new(store, config["username"], deadline)
    added += chesscom.fetch_new(store, config)
    refreshed = analyze.refresh_accuracy(store)
    if refreshed:
        print(f"Refreshed accuracy for {refreshed} games")
    imported = review.import_reviews(store)
    if imported:
        print(f"Imported {imported} reviews")
    matched = champions.assign(store)
    if matched:
        print(f"Matched champion styles for {matched} games")
    store.save()
    key = os.environ.get("OPENROUTER_API_KEY")
    test_path = ROOT / "data" / "review_test.json"
    if config.get("run_review_test") and key and not test_path.exists():
        run_review_test(store, config, key, args, test_path)
    reviewed = 0
    if config.get("reviews_enabled"):
        # Games due a review come first; the older backlog takes whatever time is left.
        stale = [g for g in review.in_scope(store, config) if review.needs_analysis(g)]
        if stale:
            analyze.analyse_pending(store, args.engine, config["engine_nodes"], args.workers, deadline, games=stale)
        reviewed = review.review_pending(store, config, key, deadline)
    analysed = analyze.analyse_pending(store, args.engine, config["engine_nodes"], args.workers, deadline)
    filled = analyze.fill_pending_mates(store, args.engine, config["engine_nodes"], args.workers, deadline)
    if filled:
        print(f"Filled mate distances for {filled} games")
    pending = sum(analyze.needs_engine(g) for g in store.games.values())
    if should_continue(store, config, key, analysed + reviewed + filled):
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a") as handle:
                handle.write("more=true\n")
    print(
        f"New games {added}, analysed {analysed}, reviewed {reviewed}. "
        f"Games stored {len(store.games)}, awaiting analysis {pending}. "
        f"Reviews total {store.state['reviews_total']}, spent ${store.state['cost_usd']:.4f}."
    )


if __name__ == "__main__":
    main()
