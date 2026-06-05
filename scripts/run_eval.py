"""Run a set of models across all tasks and score each deliverable.

For every (model, task): prepare a workspace, run the agent (via the OpenHands
harness, routed through the INFERENCE gateway), then score the deliverables
against the task's private rubric (deterministic checks + an LLM judge through
the same gateway). Writes one results/<model>__<task>.json per pair, with an
estimated cost from token usage, then you build the leaderboard from results/.

Resumable: a (model, task) whose result file already exists is skipped.

Usage:
  python scripts/run_eval.py \
    --models "gpt-4.1-mini,anthropic/claude-sonnet-4.5" \
    --judge-model anthropic/claude-sonnet-4.5 --max-iters 50
"""
from __future__ import annotations
import argparse, glob, json, os, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import run_task as rt
from eval.score import extract_deliverables, JUDGE_SYSTEM, _parse_judge
from eval.checks import run_check

# Approximate list prices, USD per 1M tokens (input, output). Cost is an estimate
# for the cost-vs-accuracy view, not a billing figure.
PRICES = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-5.5": (1.25, 10.0),
    "anthropic/claude-opus-4.8": (15.0, 75.0),
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
    "anthropic/claude-haiku-4.5": (1.0, 5.0),
}


def _price(model):
    m = model[len("openai/"):] if model.startswith("openai/") else model
    return PRICES.get(m, (0.0, 0.0))


def _gateway_client():
    from openai import OpenAI
    return OpenAI(base_url=os.environ["INFERENCE_BASE_URL"].rstrip("/") + "/v1",
                  api_key=os.environ["INFERENCE_API_KEY"])


def judge_call(client, model, criterion, deliverable_text, final_prompt):
    user = (f"TASK GIVEN TO THE AGENT:\n{final_prompt}\n\n"
            f"RUBRIC CRITERION TO GRADE:\n{criterion}\n\n"
            f"AGENT DELIVERABLE (extracted):\n{deliverable_text}\n\n"
            "Score how well the deliverable satisfies the criterion.")
    r = client.chat.completions.create(
        model=model, max_tokens=600,
        messages=[{"role": "system", "content": JUDGE_SYSTEM},
                  {"role": "user", "content": user}])
    raw = (r.choices[0].message.content or "").strip()
    score, rationale = _parse_judge(raw)
    u = r.usage
    return (0.0 if score is None else max(0.0, min(1.0, score))), \
           (rationale or "")[:300], (u.prompt_tokens or 0), (u.completion_tokens or 0)


def score_outputs(outputs_dir, rubric, final_prompt, judge_model, client):
    deliverable = None
    results, total_w, total_ws = [], 0.0, 0.0
    by_cat, jin, jout = {}, 0, 0
    for c in rubric:
        w = float(c.get("weight", 1))
        if "check" in c:
            s, detail = run_check(c["check"], outputs_dir); mode = "check"
        else:
            if deliverable is None:
                deliverable = extract_deliverables(outputs_dir)
            s, detail, ti, to = judge_call(client, judge_model, c["criterion"], deliverable, final_prompt)
            jin += ti; jout += to; mode = "judge"
        total_w += w; total_ws += w * s
        by_cat.setdefault(c.get("category", "Uncategorized"), []).append(s)
        results.append({"criterion": c["criterion"], "category": c.get("category"),
                        "weight": w, "mode": mode, "score": round(s, 3), "detail": detail})
    task_score = round(total_ws / total_w, 4) if total_w else 0.0
    cat = {k: round(sum(v) / len(v), 4) for k, v in by_cat.items()}
    return task_score, cat, results, jin, jout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="comma-separated gateway model names")
    ap.add_argument("--tasks", default="data/tasks.test.jsonl")
    ap.add_argument("--judge-model", default="anthropic/claude-sonnet-4.5")
    ap.add_argument("--rubric-dir", default="rubrics")
    ap.add_argument("--max-iters", type=int, default=50)
    ap.add_argument("--workspaces", default="workspaces")
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in open(args.tasks) if l.strip()]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    os.makedirs(args.out_dir, exist_ok=True)
    client = _gateway_client()
    jip, jop = _price(args.judge_model)

    for model in models:
        safe = model.replace("/", "-").replace(".", "_")
        for task in tasks:
            tid = task["task_id"]
            out_path = os.path.join(args.out_dir, f"{safe}__{tid}.json")
            if os.path.exists(out_path):
                print(f"[skip] {safe} {tid} (exists)", flush=True); continue
            print(f"[run ] {model} on {tid} ...", flush=True)
            ws = rt.prepare_workspace(task, "realistic", os.path.join(args.workspaces, safe))
            stats = {}
            try:
                rt.run_with_openhands(ws, model=model, max_iterations=args.max_iters, stats_out=stats)
            except Exception as e:
                print(f"  [agent error] {type(e).__name__}: {str(e)[:140]}", flush=True)
            outputs = os.path.join(ws, "outputs")
            rubric = json.load(open(os.path.join(args.rubric_dir, f"{tid}.json")))
            try:
                ts, cat, crits, jin, jout = score_outputs(
                    outputs, rubric, task["final_prompt"], args.judge_model, client)
            except Exception as e:
                print(f"  [score error] {type(e).__name__}: {str(e)[:140]}", flush=True)
                traceback.print_exc(); continue
            ain, aout = stats.get("input_tokens", 0) or 0, stats.get("output_tokens", 0) or 0
            # prefer OpenHands' own agent cost; else estimate from tokens x list price
            agent_cost = stats.get("agent_cost")
            if agent_cost is None:
                aip, aop = _price(model)
                agent_cost = (ain * aip + aout * aop) / 1e6
            cost = round(agent_cost + (jin * jip + jout * jop) / 1e6, 4)
            rec = {"task_id": tid, "workflow_cat": task.get("workflow_cat"),
                   "product": task.get("product"), "task_score": ts, "by_category": cat,
                   "cost_usd": cost, "agent_tokens": [ain, aout], "judge_tokens": [jin, jout],
                   "model": model, "judge_model": args.judge_model, "criteria": crits}
            json.dump(rec, open(out_path, "w"), indent=2)
            print(f"  -> {tid}: score {ts}  cost ~${cost}  -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
