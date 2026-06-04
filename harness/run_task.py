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

# Real data-tool implementations (SEC EDGAR, free/public). See harness/tools_edgar.py.
# Imported lazily-safe: if the module is missing the stubs below still raise clearly.
try:
    from harness import tools_edgar as _edgar
except Exception:  # pragma: no cover - allows the file to load standalone
    try:
        import tools_edgar as _edgar  # when run from inside harness/
    except Exception:
        _edgar = None

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
    """Search/fetch SEC filings. Backed by SEC EDGAR's public submissions API."""
    if _edgar is None:
        raise RuntimeError("harness/tools_edgar.py not importable; cannot run edgar_search.")
    return _edgar.edgar_search(**kwargs)


def market_data(**kwargs):
    """Company fundamentals from SEC EDGAR XBRL facts (free, no key).

    EDGAR is filings only: it returns reported financials, not market prices or
    sell-side consensus. Price/consensus fields raise a clear error directing you
    to wire a market-data vendor (we do not bundle licensed data). See
    harness/tools_edgar.py.
    """
    if _edgar is None:
        raise RuntimeError("harness/tools_edgar.py not importable; cannot run market_data.")
    return _edgar.market_data(**kwargs)


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

def _preflight_openhands():
    """Verify the OpenHands runtime, Docker, and an API key are all present.

    Returns (ok: bool, problems: list[str]). Running the agent costs money (it
    drives a real model), so callers should surface these before spending.
    """
    problems = []
    try:
        import openhands  # noqa: F401
    except Exception:
        problems.append("openhands not installed (needs Python 3.12+: `pip install openhands-ai`).")
    if shutil.which("docker") is None:
        problems.append("docker CLI not found; install Docker Desktop and start it.")
    else:
        import subprocess
        if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
            problems.append("docker daemon not running; start Docker Desktop.")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")):
        problems.append("no ANTHROPIC_API_KEY / LLM_API_KEY set for the agent model.")
    return (not problems), problems


def run_with_openhands(workspace: str, model: str, max_iterations: int = 100):
    """Run the agent inside OpenHands against the prepared workspace.

    Reference path: OpenHands (Docker-sandboxed bash + file editing), same as
    Vibe Code Bench and BTB. This drives a real model and therefore SPENDS money.

    Flow (OpenHands headless / programmatic API; pin a version, the API moves):
      1. Preflight: runtime + Docker + API key must be present (cheap, no spend).
      2. Build an LLM config for `model` (ANTHROPIC_API_KEY) and an AgentConfig
         whose workspace mount is `workspace/`; bash + file editing are built in.
      3. Register TOOLS as MCP tools / custom actions so the agent can call
         edgar_search / market_data (dispatch through TOOL_IMPLS).
      4. Seed the conversation with final_prompt.txt; instruct the agent to write
         deliverables into `workspace/outputs/`.
      5. Run up to max_iterations (or a wall-clock budget), then stop.
    Returns the path to the outputs directory.
    """
    ok, problems = _preflight_openhands()
    if not ok:
        raise RuntimeError(
            "OpenHands runtime not ready:\n  - " + "\n  - ".join(problems) +
            "\nThis path spends API credits once it runs. Prompt is at "
            f"{os.path.join(workspace, 'final_prompt.txt')}; deliverables go to "
            f"{os.path.join(workspace, 'outputs')}.")

    # --- runtime wiring (executed only once preflight passes) -------------------
    # Pinned against the OpenHands programmatic API. Kept import-local so the
    # module imports fine without OpenHands installed.
    from openhands.core.config import AppConfig, AgentConfig, LLMConfig  # type: ignore
    from openhands.core.main import run_controller  # type: ignore
    from openhands.events.action import MessageAction  # type: ignore

    outputs = os.path.join(workspace, "outputs")
    prompt = open(os.path.join(workspace, "final_prompt.txt")).read()

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")
    llm = LLMConfig(model=model, api_key=api_key)
    config = AppConfig(
        llm=llm,
        default_agent="CodeActAgent",
        max_iterations=max_iterations,
        workspace_base=workspace,            # agent's cwd; it writes to outputs/
        agents={"CodeActAgent": AgentConfig()},
    )
    # TOOLS / TOOL_IMPLS are exposed to the agent as MCP tools by your OpenHands
    # MCP config (point an MCP server at TOOL_IMPLS). See README "Wire the data tools".
    import asyncio
    asyncio.run(run_controller(
        config=config,
        initial_user_action=MessageAction(content=prompt),
    ))
    return outputs


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
