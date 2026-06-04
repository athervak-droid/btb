# CLAUDE.md

Standing context for Claude Code (read automatically at the start of each session).

## What this is
A BankerToolBench-style benchmark for evaluating AI agents on investment-banking
work. Each task is a terse, realistic prompt; the agent produces Excel / PowerPoint /
Word deliverables using a sandboxed harness with data tools; deliverables are scored
against an expert rubric. Full design is in README.md.

## Commands
- `bash setup.sh` - install Python deps
- Score a deliverable:
  `python -m eval.score --task-id <id> --rubric rubrics/<id>.json --outputs <dir> --out results/<model>__<id>.json`
- Prepare/run a rollout:
  `python harness/run_task.py --tasks data/tasks.test.jsonl --model <model> --mode realistic`
- Build the leaderboard:
  `python scripts/leaderboard.py --results results/ --out results/leaderboard.json`

## Architecture
- `data/` - tasks in JSONL. Public `tasks.test.jsonl` is final_prompt + metadata only; rubrics and contexts are private (`tasks.private.jsonl`, gitignored). Build both from the authoring spreadsheet with `scripts/ingest_tasks.py`.
- `harness/run_task.py` - prepares a workspace + tool defs, runs the agent via OpenHands, collects outputs. `harness/tools_edgar.py` - SEC EDGAR data tools.
- `eval/checks.py` - deterministic checks; `eval/score.py` - routes each rubric criterion to a check or an LLM judge, weighted.
- `scripts/leaderboard.py` - aggregates results into `leaderboard.json` (overall, per-category, cost/Pareto).
- `rubrics/` - grading keys, one `<task_id>.json` per task. All private; `.gitignore` excludes the whole folder.

## Conventions
- The agent only ever sees `final_prompt` in realistic mode. Any non-public number a rubric
  checks must be stated in the prompt or be pullable via a tool.
- Dataset text is plain and human, with no em dashes.
- Keep test-set rubrics and any golden outputs out of git; serve them at score time.
- Code is MIT. Do not bundle licensed market data; call a tool or state values in-task.

## What I want help with
1. Publish this repo to GitHub (see RUNBOOK.md).
2. Wire `edgar_search` and `market_data` in `harness/run_task.py` to SEC EDGAR and a
   market-data source, hook up the OpenHands runtime, then run a task end to end and score it.
3. Build a Next.js leaderboard that reads `results/leaderboard.json` (table plus a
   cost-vs-accuracy scatter) and deploy it to Vercel.

## Important
Always confirm with me before anything that pushes to a remote, deploys, grants
permissions, or spends money. I authenticate GitHub and Vercel myself; use those sessions.
