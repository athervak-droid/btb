"""Rollout harness: run an agent against a task.

This prepares a sandboxed workspace (the final_prompt, any input files, and the
data tools) and hands execution to an agent harness. Vibe Code Bench and BTB both
run on OpenHands (Docker-in-Docker), which gives the agent isolated bash + file
access; that is the recommended path and is wired below as an adapter. The data
tools (SEC EDGAR, market data) are defined here as stubs for you to point at your
own sources.

Nothing in this file executes model-generated code directly; that is the agent
harness's job inside its sandbox.

Usage:
    python harness/run_task.py --tasks data/tasks.test.jsonl --model <model> --mode realistic
"""
from __future__ import annotations
import argparse
import json
import os
import shutil

# ----------------------------- tool registry (stubs) -----------------------------
# Expose these to the agent in your harness. Each should return real data; here
# they raise so you remember to wire them. SEC EDGAR is public and redistributable;
# do NOT bundle licensed market data, call a vendor API at runtime instead.

TOOLS = [
    {
        "name": "edgar_search",
        "description": "Search and fetch SEC filings (10-K, 10-Q, 8-K, proxy) for a US public company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker_or_cik": {"type": "string"},
                "form_type": {"type": "string", "description": "e.g. 10-K, 10-Q, 8-K, DEFM14A"},
                "as_of": {"type": "string", "description": "YYYY-MM-DD; most recent on/before this date"},
            },
            "required": ["ticker_or_cik"],
        },
    },
    {
        "name": "market_data",
        "description": "Fetch prices, financials, and consensus estimates for a US public company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "field": {"type": "string", "description": "e.g. close_price, ltm_ebitda, net_debt, shares_diluted"},
                "as_of": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["ticker", "field"],
        },
    },
]


def edgar_search(**kwargs):
    raise NotImplementedError("Point edgar_search at your SEC EDGAR copy / the EDGAR full-text API.")


def market_data(**kwargs):
    raise NotImplementedError("Point market_data at your market-data source (public or licensed-at-runtime).")


TOOL_IMPLS = {"edgar_search": edgar_search, "market_data": market_data}


# ----------------------------- workspace prep -----------------------------

def prepare_workspace(task: dict, mode: str, root: str) -> str:
    """Create workspace/<task_id> with the prompt, inputs, and an empty outputs dir."""
    ws = os.path.join(root, task["task_id"])
    os.makedirs(os.path.join(ws, "outputs"), exist_ok=True)
    os.makedirs(os.path.join(ws, "inputs"), exist_ok=True)

    prompt = task["final_prompt"]
    if mode == "scaffolded":
        # only in the ablation mode do we reveal the withheld fields
        extra = []
        if task.get("prompt_context"):
            extra.append("CONTEXT:\n" + task["prompt_context"])
        if task.get("formatting_context"):
            extra.append("FORMATTING:\n" + task["formatting_context"])
        if extra:
            prompt = prompt + "\n\n" + "\n\n".join(extra)
    with open(os.path.join(ws, "final_prompt.txt"), "w") as f:
        f.write(prompt)

    # copy any provided input files for this task
    src = os.path.join("data", "task-data", task["task_id"], "Inputs")
    if os.path.isdir(src):
        for name in os.listdir(src):
            shutil.copy2(os.path.join(src, name), os.path.join(ws, "inputs", name))
    return ws


# ----------------------------- OpenHands adapter -----------------------------

def run_with_openhands(workspace: str, model: str, max_iterations: int = 100):
    """Run the agent inside OpenHands against the prepared workspace.

    Integration outline (see https://github.com/OpenHands/OpenHands):
      1. Mount `workspace/` as the agent's working directory.
      2. Register TOOLS above as MCP tools (or OpenHands custom actions) so the
         agent can call edgar_search / market_data; bash + file editing are
         built in. Instruct it to write final deliverables into `workspace/outputs/`.
      3. Seed the conversation with the contents of `final_prompt.txt`.
      4. Run up to `max_iterations` (or a wall-clock budget), then stop.
    Returns the path to the outputs directory.
    """
    raise NotImplementedError(
        "Wire this to your OpenHands runtime. Prompt is at "
        f"{os.path.join(workspace, 'final_prompt.txt')}; deliverables go to "
        f"{os.path.join(workspace, 'outputs')}."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, help="tasks jsonl")
    ap.add_argument("--model", required=True)
    ap.add_argument("--mode", choices=["realistic", "scaffolded"], default="realistic")
    ap.add_argument("--workspaces", default="workspaces")
    args = ap.parse_args()

    with open(args.tasks) as f:
        tasks = [json.loads(line) for line in f if line.strip()]

    for task in tasks:
        ws = prepare_workspace(task, args.mode, args.workspaces)
        print(f"[prepared] {task['task_id']} -> {ws}  (mode={args.mode})")
        # run_with_openhands(ws, args.model)   # enable once your harness is wired
        print(f"  next: run the agent, then score with:")
        print(f"    python -m eval.score --task-id {task['task_id']} --tasks {args.tasks} "
              f"--outputs {os.path.join(ws, 'outputs')} --out results/{args.model}__{task['task_id']}.json")


if __name__ == "__main__":
    main()
