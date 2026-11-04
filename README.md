# pinkroses-lichess

Tracks every Lichess game played by [PinkRoses](https://lichess.org/@/PinkRoses), checks each one with Stockfish, and publishes a written review of it, along with rating trends and recurring mistakes, as a GitHub Pages site.

**Live site:** https://kennethkimbrough.github.io/pinkroses-lichess/

## How it works

Every two hours a GitHub Action:

1. Downloads new games from the public Lichess API.
2. Runs Stockfish 17.1 on each position (100,000 nodes) to find mistakes, blunders and the moves the engine preferred.
3. Sends the annotated game to `google/gemini-3.7-flash` through OpenRouter for a review of how the game unfolded. A review is rejected and retried if it cites a move that isn't in the game or an engine line, or names a pin, skewer, fork, discovered attack or back-rank tactic the board doesn't show. Reviews cover the latest 50 games at setup, every game after them, and all rapid and classical games.
4. Commits the results to `data/` and publishes the site from `site/`.

While work remains, each productive run queues the next one, so backlogs don't depend on the schedule. A run with no new games changes nothing and costs nothing. Older games are analysed newest first across runs and count toward the stats. If the repo has been quiet for 50 days, a small commit keeps the schedule from being disabled.

Accuracy follows the Lichess method, but on separate engine analysis, so it can differ slightly from the figure Lichess shows.

## Setup

1. Add an `OPENROUTER_API_KEY` repository secret, ideally from a key with its own spending limit.
2. Set **Settings > Pages > Source** to **GitHub Actions**.
3. Run **Update games** from the Actions tab, or wait for the schedule.

## Settings

All of these are in `config.json`:

| Setting | Meaning |
|---|---|
| `reviews_enabled` | Turns ongoing reviews on or off. |
| `review_latest` | How many recent games to review when reviews first start. |
| `review_all_speeds` | Time controls to review across the full history. |
| `monthly_limit_usd` | Pauses reviews until next month after this much spending. |
| `monthly_limit_overrides` | A different limit for a named month, such as `2026-11`. |
| `max_cost_usd` | Stops reviews once total tracked spending reaches this amount. |
| `reasoning` | Extra model reasoning: `off`, `low`, `medium` or `high`. |
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
