"""Builds tracker/champions.json from PGN files named after each champion.

Usage: python tools/build_champion_profiles.py PGN_FOLDER [--evaluate]
"""
import io
import json
import random
import re
import sys
from pathlib import Path

import chess
import chess.pgn
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tracker import champions  # noqa: E402

NAMES = {"Steinitz": "Wilhelm Steinitz", "Lasker": "Emanuel Lasker", "Capablanca": "José Raúl Capablanca",
         "Alekhine": "Alexander Alekhine", "Euwe": "Max Euwe", "Botvinnik": "Mikhail Botvinnik",
         "Smyslov": "Vasily Smyslov", "Tal": "Mikhail Tal", "Petrosian": "Tigran Petrosian",
         "Spassky": "Boris Spassky", "Fischer": "Bobby Fischer", "Karpov": "Anatoly Karpov",
         "Kasparov": "Garry Kasparov", "Kramnik": "Vladimir Kramnik", "Anand": "Viswanathan Anand",
         "Carlsen": "Magnus Carlsen"}
LIMIT = 1200


def load(path, surname, rng):
    text = path.read_text(errors="replace")
    chunks = re.split(r"(?=^\[Event )", text, flags=re.M)
    chunks = [c for c in chunks if c.strip()]
    rng.shuffle(chunks)
    rows = []
    for chunk in chunks:
        if len(rows) >= LIMIT:
            break
        game = chess.pgn.read_game(io.StringIO(chunk))
        if game is None or game.errors or "FEN" in game.headers:
            continue
        white, black = game.headers.get("White", ""), game.headers.get("Black", "")
        if white.startswith(surname):
            color = chess.WHITE
        elif black.startswith(surname):
            color = chess.BLACK
        else:
            continue
        board, sans = game.board(), []
        for move in game.mainline_moves():
            sans.append(board.san(move))
            board.push(move)
        features = champions.extract(sans, color)
        if features:
            rows.append(features)
    return rows


def matrix(rows, overall):
    return np.array([[(row[n] - overall[n][0]) / overall[n][1] for n in champions.FEATURES] for row in rows])


def train(rows, overall, steps=1500, rate=0.3, decay=0.002):
    """Class-balanced softmax regression, so champions with more games aren't favored."""
    names = list(rows)
    x = np.vstack([matrix(rows[n], overall) for n in names])
    y = np.concatenate([[i] * len(rows[n]) for i, n in enumerate(names)])
    sample = np.concatenate([[1 / len(rows[n])] * len(rows[n]) for n in names])
    sample = sample / sample.sum()
    weights, bias = np.zeros((x.shape[1], len(names))), np.zeros(len(names))
    for _ in range(steps):
        logits = x @ weights + bias
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        target = np.zeros_like(p)
        target[np.arange(len(y)), y] = 1
        error = (p - target) * sample[:, None]
        weights -= rate * (x.T @ error + decay * weights) * 3
        bias -= rate * error.sum(axis=0) * 3
    return {n: {"bias": round(float(bias[i]), 4), "weights": [round(float(w), 4) for w in weights[:, i]]}
            for i, n in enumerate(names)}


def main():
    folder = Path(sys.argv[1])
    rng = random.Random(7)
    rows = {surname: load(folder / f"{surname}.pgn", surname, rng) for surname in NAMES}
    everyone = [row for games in rows.values() for row in games]
    overall = champions.fit(everyone)
    if "--evaluate" in sys.argv:
        training, test = {}, {}
        for surname, games in rows.items():
            cut = len(games) // 5
            test[surname], training[surname] = games[:cut], games[cut:]
        data = {"overall": overall, "models": train(training, overall)}
        hits = top3 = 0
        per = []
        for surname, games in test.items():
            own = 0
            for row in games:
                ranked = [n for n, _ in champions.rank(row, data)]
                hits += ranked[0] == surname
                own += ranked[0] == surname
                top3 += surname in ranked[:3]
            per.append(own / max(len(games), 1))
            print(f"{surname:12} {len(rows[surname]):5} games, held-out top match {per[-1]:.0%}")
        print(f"Average per champion: top match {sum(per) / len(per):.1%}. All games: top {hits / sum(map(len, test.values())):.1%}, "
              f"top three {top3 / sum(map(len, test.values())):.1%}. Chance {1 / len(rows):.1%} and {3 / len(rows):.1%}")
    models = train(rows, overall)
    output = {
        "overall": overall,
        "models": {NAMES[s]: models[s] for s in rows},
        "champions": {NAMES[s]: champions.fit(g) for s, g in rows.items()},
        "games": {NAMES[s]: len(g) for s, g in rows.items()},
    }
    champions.PROFILE_PATH.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
