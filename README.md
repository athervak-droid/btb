# BankerToolBench-Style Agent Benchmark (starter)

An end-to-end benchmark for evaluating AI agents on investment-banking work,
modeled on BankerToolBench and the Vibe Code Bench setup. Each task is a terse,
realistic ask (the kind a first-year actually gets), the agent produces
multi-file deliverables (Excel / PowerPoint / Word) using a sandboxed harness
with data tools, and the deliverables are scored against an expert rubric.

## How it works

```
 data/tasks.*.jsonl        harness/ (OpenHands)         eval/
 ┌───────────────┐         ┌──────────────────┐        ┌─────────────────┐
 │ final_prompt  │ ──────► │ agent + tools     │ ─────► │ score.py        │
 │ (+ input files)│        │ (EDGAR, mkt data, │ files  │  ├ checks.py     │ ──► results/*.json
 │  ONLY this is  │        │  file creation)   │ .xlsx  │  └ LLM judge     │      └─► scripts/leaderboard.py
 │  shown to agent│        └──────────────────┘ .pptx  │ vs rubric       │
 └───────────────┘                               .docx └─────────────────┘
```

1. **Rollout** (`harness/run_task.py`): drop the agent into an isolated workspace
   with the `final_prompt`, any provided input files, and the data tools. It works
   for a turn/time budget and writes its deliverables to `outputs/`.
2. **Score** (`eval/score.py`): each rubric criterion is either checked
   deterministically (`eval/checks.py`) or graded by an LLM judge. Weighted, per
   task and per category.
3. **Aggregate** (`scripts/leaderboard.py`): mean score across tasks, broken out
   by workflow category, plus cost, for a leaderboard and a cost-vs-accuracy
   (Pareto) view.

## Two evaluation modes

- **Realistic (canonical):** the agent sees only `final_prompt` (+ input files +
  tools). This is the real test: can it infer methodology, apply standard
  conventions, and pull its own data from a vague ask.
- **Scaffolded (ablation):** also feed `prompt_context` and `formatting_context`.
  Useful to separate "couldn't infer the convention" from "couldn't execute."

Set the mode with `--mode realistic|scaffolded`.

## Repo layout

```
data/
  tasks.test.jsonl     # PUBLIC test set: final_prompt + metadata only (no rubric/context/answers)
  tasks.private.jsonl  # PRIVATE (gitignored): full records incl. prompt/formatting context + rubric pointer
  task-data/<id>/Inputs/   # input files handed to the agent for that task (if any)
rubrics/
  <id>.json            # rubric: [{criterion, category, weight, check?}]  (PRIVATE, gitignored)
harness/
  run_task.py          # rollout: build workspace + tools, run via OpenHands, collect outputs
  tools_edgar.py       # SEC EDGAR data tools (edgar_search, market_data)
eval/
  checks.py            # deterministic checks against deliverables (openpyxl, etc.)
  score.py             # route each criterion (check vs judge), weighted aggregate
scripts/
  ingest_tasks.py      # import the authoring spreadsheet -> public tasks + private rubrics
  leaderboard.py       # aggregate results across models/tasks -> leaderboard + Pareto data
results/               # per-model, per-task score JSON (gitignored)
```

## Public vs private (benchmark integrity)

Publishing the rubrics and answer values lets models be tuned to them and
contaminates the benchmark. The split:

- **Public (committed):** `tasks.test.jsonl` (final_prompt + product/category only,
  no rubric/context/answers), the harness, and the eval code.
- **Private (NOT committed, served at score time):** every rubric, any golden
  outputs, and the `prompt_context`/`formatting_context` fields (in
  `tasks.private.jsonl`). `.gitignore` excludes `rubrics/`, `results/`, and
  `tasks.private.jsonl`; keep the real rubrics in a private store and point
  `score.py --rubric` at them server-side.

## Data schema

`tasks.*.jsonl`, one JSON object per line:

| field | shown to agent? | notes |
|---|---|---|
| `task_id` | no | unique id |
| `final_prompt` | **yes** | the ask; the only task text the agent sees in realistic mode |
| `prompt_context` | scaffolded only | assumptions / answer-key scaffolding |
| `formatting_context` | scaffolded only | house style |
| `product` | no | one of a fixed set (M&A, DCM, ECM, LevFin, Restructuring) |
| `workflow_cat` | no | category, for leaderboard slicing |
| `workflow_subcat` | no | subcategory |
| `aggregated_rubric_json` | no (grading key) | inline rubric, or use a `rubrics/<id>.json` file |

**Rubric format** (`rubrics/<id>.json`), a list of criteria:

```json
[
  {"criterion": "Negative numbers shown in parentheses, not minus signs",
   "category": "Client Readiness", "weight": 3,
   "check": {"type": "negatives_in_parentheses", "file": "*.xlsx"}},

  {"criterion": "Comp set is a defensible selection of recent large-cap midstream deals",
   "category": "Technical Correctness", "weight": 10}
]
```

A criterion with a `check` block is graded deterministically; one without is sent
to the LLM judge. That split is what makes scoring cheap where it can be and
flexible where it has to be.

## Quickstart

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # for the LLM judge (and the reference harness)

# 1) score an already-produced deliverable against a rubric (rubrics are private)
python -m eval.score \
  --task-id T-001 \
  --rubric rubrics/T-001.json \
  --outputs path/to/agent_outputs/ \
  --out results/claude__T-001.json

# 2) run the full rollout (requires OpenHands installed; see harness/run_task.py)
python harness/run_task.py --tasks data/tasks.test.jsonl --model <model> --mode realistic

# 3) build the leaderboard from results/
python scripts/leaderboard.py --results results/ --out results/leaderboard.json
```

## Extending it

- **Add a task:** append a row to `tasks.test.jsonl` (and a private rubric). Keep
  the `final_prompt` to what an MD would actually say, and make sure every
  non-public number the rubric checks is stated in the prompt or pullable via a
  tool (the agent never sees `prompt_context`).
- **Add a deterministic check:** add a function in `eval/checks.py` and register it
  in the dispatch table; reference it from a rubric criterion's `check.type`.
- **Data tools:** `edgar_search` and `market_data` are wired to SEC EDGAR
  (public, free, no key) in `harness/tools_edgar.py` using the standard library
  only. `edgar_search` resolves a ticker to a CIK and lists filings; `market_data`
  pulls reported fundamentals from EDGAR's XBRL facts (revenue, net income, shares,
  cash, debt, and derived net_debt / EBITDA / leverage / coverage). **Set a
  contact User-Agent** or SEC will 403 you:
  `export SEC_USER_AGENT="your name (you@example.com)"`. Smoke-test it free with
  `python harness/tools_edgar.py OKE`.
  - **Prices:** EDGAR has no market prices, so `market_data` serves `close_price`,
    `market_cap`, and `enterprise_value` from [Tiingo](https://www.tiingo.com)
    (free tier) when `TIINGO_API_KEY` is set; pass `as_of=YYYY-MM-DD` for a
    historical close (e.g. an unaffected price). Without the key these fields
    raise with a clear message.
  - **Consensus/estimates** are licensed with no free source: state them in the
    task prompt as given assumptions (the benchmark allows prompt-stated inputs).
    Do not redistribute licensed market data.
- **Swap the harness:** the reference path uses OpenHands (Docker-in-Docker,
  sandboxed) like Vibe Code Bench and BTB. Any agent harness works as long as it
  takes the prompt + tools and writes files to `outputs/`.

## Scoring details

- Task score = sum(weight x criterion_score) / sum(weight), where criterion_score
  is in [0, 1] (1/0 for deterministic, judge-assigned for the rest).
- Reported per task, averaged for the headline, and broken out by `workflow_cat`.
- Track tokens/cost per rollout so you can plot cost vs accuracy.

## Licensing

Code: MIT (edit `LICENSE`). Data: BankerToolBench uses CC-BY-4.0; pick your own.
Underlying facts come from public SEC filings. Do not bundle licensed market data
or vendor consensus estimates; serve those via a tool or state them in-task.
