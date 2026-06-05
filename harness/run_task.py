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

    # drop the EDGAR data tools into the workspace so the agent can import them
    # (stdlib-only, no key). The agent calls them from its terminal; see _ENV_PREAMBLE.
    tools_src = os.path.join(os.path.dirname(__file__), "tools_edgar.py")
    if os.path.isfile(tools_src):
        shutil.copy2(tools_src, os.path.join(ws, "tools_edgar.py"))
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
    # Docker is only required when running the agent in a containerized workspace;
    # a LocalWorkspace run does not need it. We still report it so the sandboxed
    # path is available.
    if shutil.which("docker") is None:
        problems.append("docker CLI not found (needed only for a sandboxed workspace; "
                        "install Docker Desktop or `brew install colima docker` + `colima start`).")
    else:
        import subprocess
        if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
            problems.append("docker daemon not running; start it (`colima start` or Docker Desktop).")
    if not (os.environ.get("INFERENCE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("LLM_API_KEY")):
        problems.append("no INFERENCE_API_KEY / ANTHROPIC_API_KEY / LLM_API_KEY set for the agent model.")
    return (not problems), problems


# Tells the agent where to write and that the EDGAR tools are on hand. This is
# harness scaffolding (tools + output location), NOT task content: it carries no
# rubric answer and is kept separate from the graded final_prompt.
_ENV_PREAMBLE = (
    "You are running headless in a sandboxed workspace.\n\n"
    "Two data tools are available as a local Python module, tools_edgar.py, in the "
    "workspace (SEC EDGAR, free, no key). Call them from the terminal, e.g.:\n"
    "  python -c \"from tools_edgar import edgar_search, market_data; "
    "import json; print(json.dumps(edgar_search('OKE', form_type='10-K', limit=3), indent=2))\"\n"
    "  python -c \"from tools_edgar import market_data; "
    "print(market_data('OKE', 'net_debt'))\"\n"
    "edgar_search(ticker_or_cik, form_type=None, as_of=None) lists filings; "
    "market_data(ticker, field, as_of=None) returns fundamentals (revenue, "
    "net_income, shares_diluted, cash, net_debt, ebitda, net_debt_to_ebitda, "
    "interest_coverage, ...) from EDGAR, and market prices (close_price, "
    "market_cap, enterprise_value) from a price vendor when configured - pass "
    "as_of=YYYY-MM-DD for a historical close (e.g. an unaffected price). Sell-side "
    "consensus has no data source and raises; use any consensus figures stated in "
    "the task prompt.\n"
)


def run_with_openhands(workspace: str, model: str, max_iterations: int = 100, stats_out: dict = None):
    """Run the agent against the prepared workspace via the OpenHands SDK.

    Targets openhands-ai 1.7.x (OpenHands software-agent SDK 1.19.x), whose API
    lives under `openhands.sdk`. This drives a real model and therefore SPENDS
    money once preflight passes.

    Flow:
      1. Preflight (cheap, no spend): runtime + API key present.
      2. Build an LLM for `model` from ANTHROPIC_API_KEY / LLM_API_KEY.
      3. Default agent = terminal + file_editor + task_tracker tools, running in
         `workspace` (a LocalWorkspace; point this at a Docker/remote workspace
         for stronger isolation - Colima provides the engine).
      4. Seed an environment preamble (output dir + EDGAR tools), then the task
         prompt, and run to completion (bounded by max_iterations).
    Returns the path to the outputs directory.
    """
    ok, problems = _preflight_openhands()
    # Docker is optional for a LocalWorkspace run; only the runtime + key are hard
    # requirements here. Surface any docker note but don't block on it.
    hard = [p for p in problems if "docker" not in p.lower()]
    if hard:
        raise RuntimeError(
            "OpenHands runtime not ready:\n  - " + "\n  - ".join(hard) +
            "\nThis path spends API credits once it runs. Prompt is at "
            f"{os.path.join(workspace, 'final_prompt.txt')}; deliverables go to "
            f"{os.path.join(workspace, 'outputs')}.")

    # Import-local so this module loads fine without OpenHands installed.
    from pydantic import SecretStr
    from openhands.sdk import LLM, Conversation  # type: ignore
    from openhands.tools.preset.default import get_default_agent  # type: ignore

    workspace = os.path.abspath(workspace)  # OpenHands LocalWorkspace needs an absolute dir
    outputs = os.path.join(workspace, "outputs")
    os.makedirs(outputs, exist_ok=True)
    prompt = open(os.path.join(workspace, "final_prompt.txt")).read()

    # Route through an OpenAI-compatible gateway (INFERENCE_BASE_URL) if set, so
    # `model` can be any model the gateway fronts (e.g. "gpt-5.5",
    # "anthropic/claude-opus-4.8"). litellm reaches a custom OpenAI endpoint via
    # the "openai/<model>" prefix. Else use ANTHROPIC_API_KEY directly.
    base = os.environ.get("INFERENCE_BASE_URL")
    if base:
        llm = LLM(model="openai/" + model,
                  base_url=base.rstrip("/") + "/v1",
                  api_key=SecretStr(os.environ.get("INFERENCE_API_KEY")),
                  usage_id="agent", max_message_chars=30000)
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")
        llm = LLM(model=model, api_key=SecretStr(api_key), usage_id="agent",
                  max_message_chars=30000)
    agent = get_default_agent(llm=llm, cli_mode=True)  # cli_mode: no browser GUI
    conversation = Conversation(agent=agent, workspace=workspace,
                                max_iteration_per_run=max_iterations)
    where = (f"Your working directory is: {workspace}\n"
             f"Write EVERY final deliverable into this exact directory: {outputs}\n"
             f"Use that absolute path; do NOT invent a /workspace path. Only files "
             f"there are collected and graded.\n\n")
    conversation.send_message(where + _ENV_PREAMBLE + "\nTASK:\n" + prompt)
    conversation.run()
    if stats_out is not None:
        stats_out["conversation"] = conversation
        try:  # best-effort token capture for cost; structure varies by SDK version
            st = getattr(conversation, "conversation_stats", None) or \
                 getattr(getattr(conversation, "state", None), "stats", None)
            metrics = getattr(st, "get_combined_metrics", lambda: None)() if st else None
            usage = getattr(metrics, "accumulated_token_usage", None) if metrics else None
            if usage is not None:
                stats_out["input_tokens"] = getattr(usage, "prompt_tokens", 0)
                stats_out["output_tokens"] = getattr(usage, "completion_tokens", 0)
            if metrics is not None:  # OpenHands' own cost calc, when it knows the model price
                stats_out["agent_cost"] = getattr(metrics, "accumulated_cost", None)
        except Exception as e:
            stats_out["stats_error"] = str(e)
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
