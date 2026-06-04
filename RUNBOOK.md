# Runbook: publish, run, and deploy with Claude Code

Everything below runs on your machine. You authenticate to GitHub and Vercel
yourself; Claude Code then uses those sessions. The prompts in quotes are what you
type to Claude Code once it's running.

## 0. Install Claude Code
Official setup: https://code.claude.com/docs/en/setup

Quick path: use the native installer (macOS, Linux, Windows) from that page, or
`npm install -g @anthropic-ai/claude-code` (needs Node.js 18+). Then `cd` into this
folder and run `claude`. You authenticate with a paid Claude plan (Pro, Max, Team,
or Enterprise) or a Console/API account; the free Claude.ai plan does not include
Claude Code. Run `claude doctor` if anything looks off.

## 1. Open the project
```
cd banker-tool-bench
bash setup.sh        # installs Python deps
claude               # starts Claude Code; it auto-reads CLAUDE.md for context
```

## 2. Publish to GitHub
First authenticate once yourself:
```
gh auth login        # or have your git credentials configured
```
Then in Claude Code:
> "Initialize git, make the first commit, create a public GitHub repo named
> banker-tool-bench, and push it. Before pushing, confirm .gitignore is excluding
> results/ and the private rubrics."

## 3. Run a task end to end (when your harness is wired)
You'll need an OpenHands runtime, your SEC EDGAR + market-data sources, and
`ANTHROPIC_API_KEY` for the LLM judge. In Claude Code:
> "Wire edgar_search and market_data in harness/run_task.py to <your sources> and
> hook up the OpenHands runtime in run_with_openhands. Run btb-001, then score the
> outputs with eval/score.py and show me the result JSON."

## 4. Build and deploy the leaderboard
First authenticate once yourself:
```
vercel login
```
Then in Claude Code:
> "Scaffold a minimal Next.js app that fetches results/leaderboard.json and renders
> the leaderboard table plus a cost-vs-accuracy scatter chart. Run it locally so I
> can check it, then deploy to Vercel. Confirm with me before the deploy."

## Notes
- Claude Code has direct filesystem access and can run commands. Per CLAUDE.md it
  asks before pushing, deploying, or spending; keep that guardrail.
- Work in short, focused sessions (one goal each) rather than one long run.
