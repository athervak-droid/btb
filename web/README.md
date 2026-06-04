# BankerToolBench Leaderboard (web)

Minimal Next.js (App Router) frontend that renders the benchmark leaderboard:
an overall table with per-category breakdowns and a cost-vs-accuracy scatter.

## Data

The app reads `data/leaderboard.json`, a committed snapshot of the repo's
`results/leaderboard.json` (which `scripts/leaderboard.py` produces from
per-task result files). To refresh:

```bash
# from the repo root: rebuild the leaderboard
python scripts/leaderboard.py --results results/ --out results/leaderboard.json
# from web/: copy it into the app snapshot
npm run sync
```

`results/` is gitignored, so the app keeps its own committed copy in `data/`.

## Develop

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
```

## Deploy

Deploys to Vercel as a standard Next.js app (root directory: `web`). No env vars
required; the data is bundled at build time.
