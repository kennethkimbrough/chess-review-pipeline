# pinkroses-lichess

Tracks every Lichess game played by [PinkRoses](https://lichess.org/@/PinkRoses), checks each one with Stockfish, and publishes a written review of it, along with rating trends and recurring mistakes, as a GitHub Pages site.

## How it works

Every two hours a GitHub Action:

1. Downloads new games from the public Lichess API.
2. Runs Stockfish 17.1 on each position (100,000 nodes) to find mistakes, blunders and the moves the engine preferred.
3. Sends those findings to `google/gemini-2.5-flash-lite` through OpenRouter for a short review. A review that mentions a piece move missing from the game and the findings is rejected and retried.
4. Commits the results to `data/` and publishes the site from `site/`.

A run with no new games changes nothing and costs nothing. Older games are worked through newest first across runs. If the repo has been quiet for 50 days, a small commit keeps the schedule from being disabled.

Accuracy uses the Lichess per-move formula but averages it simply, so it can differ from the figure Lichess shows.

## Setup

1. Add an `OPENROUTER_API_KEY` repository secret, ideally from a key with its own spending limit.
2. Set **Settings > Pages > Source** to **GitHub Actions**.
3. Run **Update games** from the Actions tab, or wait for the schedule.

## Settings

All of these are in `config.json`:

| Setting | Meaning |
|---|---|
| `max_reviews_total` | Stops after this many reviews in total. Set to `null` for no count limit. |
| `max_cost_usd` | Stops reviews once tracked spending reaches this amount. |
| `model` | Any OpenRouter model id. |
| `engine_nodes` | Stockfish search size per position. |
| `goal_rating` | The target shown on the site. |

## Run it locally

```sh
pip install -r requirements.txt pytest
pytest
STOCKFISH_PATH=/path/to/stockfish OPENROUTER_API_KEY=... python -m tracker run --minutes 10
python -m tracker build
python -m http.server --directory site
```

Board replay uses [chess.js](https://github.com/jhlywa/chess.js) (BSD 2-Clause, see `site/vendor`).
