"""Command line: `python -m tracker run` updates the data, `build` makes the site data."""
import argparse
import json
import os
import time
from pathlib import Path

from . import analyze, build, lichess, review
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


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
    store.save()
    analysed = 0
    if any("analysis" not in g for g in store.games.values()):
        # Reviews get the last slice of the run so each run publishes some.
        analysed = analyze.analyse_pending(
            store, args.engine, config["engine_nodes"], args.workers,
            start + (args.minutes * 60) * 0.9,
        )
    reviewed = review.review_pending(store, config, os.environ.get("OPENROUTER_API_KEY"), deadline)
    pending = sum("analysis" not in g for g in store.games.values())
    print(
        f"New games {added}, analysed {analysed}, reviewed {reviewed}. "
        f"Games stored {len(store.games)}, awaiting analysis {pending}. "
        f"Reviews total {store.state['reviews_total']}, spent ${store.state['cost_usd']:.4f}."
    )


if __name__ == "__main__":
    main()
