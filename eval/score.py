"""Score an agent's deliverables against a task rubric.

Each rubric criterion is either checked deterministically (if it has a `check`
block, handled by checks.py) or graded by an LLM judge against an extracted
representation of the deliverables. The task score is the weighted average of
criterion scores, also broken out by category.

Usage:
    python -m eval.score \
        --task-id btb-001 \
        --rubric rubrics/btb-001.json \
        --outputs path/to/agent_outputs/ \
        --out results/claude__btb-001.json \
        [--final-prompt-file prompt.txt] [--judge-model claude-sonnet-4-6]
"""
from __future__ import annotations
import argparse
import glob
import json
import os

from eval.checks import run_check

# ----------------------------- deliverable extraction -----------------------------

def _extract_xlsx(path: str, max_rows: int = 60) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    out = [f"# WORKBOOK {os.path.basename(path)}"]
    for ws in wb.worksheets:
        out.append(f"\n## SHEET: {ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                out.append("... (truncated)")
                break
            cells = [("" if v is None else str(v)) for v in row]
            if any(cells):
                out.append(" | ".join(cells))
    return "\n".join(out)


def _extract_pptx(path: str) -> str:
    from pptx import Presentation
    prs = Presentation(path)
    out = [f"# DECK {os.path.basename(path)}"]
    for n, slide in enumerate(prs.slides, 1):
        out.append(f"\n## SLIDE {n}")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                out.append(shape.text_frame.text)
    return "\n".join(out)


def _extract_docx(path: str) -> str:
    import docx
    d = docx.Document(path)
    out = [f"# DOC {os.path.basename(path)}"]
    out += [p.text for p in d.paragraphs if p.text.strip()]
    return "\n".join(out)


def extract_deliverables(outputs_dir: str, char_budget: int = 24000) -> str:
    parts = []
    for path in sorted(glob.glob(os.path.join(outputs_dir, "**", "*"), recursive=True)):
        ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
        try:
            if ext == "xlsx":
                parts.append(_extract_xlsx(path))
            elif ext == "pptx":
                parts.append(_extract_pptx(path))
            elif ext == "docx":
                parts.append(_extract_docx(path))
        except Exception as e:
            parts.append(f"# (could not read {os.path.basename(path)}: {e})")
    text = "\n\n".join(parts) if parts else "(no readable deliverables found)"
    return text[:char_budget]


# ----------------------------- LLM judge -----------------------------

JUDGE_SYSTEM = (
    "You are a meticulous managing director grading a junior banker's deliverable "
    "against one rubric criterion. Judge only that criterion. Be strict but fair: "
    "award partial credit when the work is partly right. Reply with a single JSON "
    "object and nothing else: {\"score\": <0.0-1.0>, \"rationale\": \"<one sentence>\"}."
)


def llm_judge(criterion: str, deliverable_text: str, final_prompt: str, model: str):
    from anthropic import Anthropic
    client = Anthropic()  # reads ANTHROPIC_API_KEY
    user = (
        f"TASK GIVEN TO THE AGENT:\n{final_prompt}\n\n"
        f"RUBRIC CRITERION TO GRADE:\n{criterion}\n\n"
        f"AGENT DELIVERABLE (extracted):\n{deliverable_text}\n\n"
        "Score how well the deliverable satisfies the criterion."
    )
    msg = client.messages.create(
        model=model, max_tokens=300,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        obj = json.loads(raw)
        return max(0.0, min(1.0, float(obj["score"]))), str(obj.get("rationale", ""))[:300]
    except Exception:
        return 0.0, f"judge parse error: {raw[:120]}"


# ----------------------------- orchestration -----------------------------

def load_rubric(args, task):
    if args.rubric:
        with open(args.rubric) as f:
            return json.load(f)
    if task and task.get("rubric_file"):
        with open(task["rubric_file"]) as f:
            return json.load(f)
    if task and task.get("aggregated_rubric_json"):
        return json.loads(task["aggregated_rubric_json"])
    raise SystemExit("No rubric: pass --rubric or give the task a rubric_file / aggregated_rubric_json.")


def load_task(tasks_file, task_id):
    if not tasks_file:
        return None
    with open(tasks_file) as f:
        for line in f:
            row = json.loads(line)
            if row.get("task_id") == task_id:
                return row
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--rubric", help="path to rubric JSON (else read from --tasks row)")
    ap.add_argument("--tasks", help="tasks jsonl to pull final_prompt / rubric from")
    ap.add_argument("--outputs", required=True, help="dir with the agent's deliverables")
    ap.add_argument("--final-prompt-file", help="text file with the prompt (for the judge)")
    ap.add_argument("--judge-model", default="claude-sonnet-4-6")
    ap.add_argument("--cost-usd", type=float, default=None,
                    help="rollout cost for this task; recorded so the leaderboard "
                         "can plot cost vs accuracy (the harness knows the cost, "
                         "the scorer does not)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    task = load_task(args.tasks, args.task_id)
    rubric = load_rubric(args, task)

    final_prompt = ""
    if args.final_prompt_file and os.path.exists(args.final_prompt_file):
        final_prompt = open(args.final_prompt_file).read()
    elif task:
        final_prompt = task.get("final_prompt", "")

    deliverable_text = None  # extracted lazily, only if a judge criterion needs it
    results, total_w, total_ws = [], 0.0, 0.0
    by_cat: dict[str, list[float]] = {}

    for c in rubric:
        w = float(c.get("weight", 1))
        if "check" in c:
            score, detail = run_check(c["check"], args.outputs)
            mode = "check"
        else:
            if deliverable_text is None:
                deliverable_text = extract_deliverables(args.outputs)
            score, detail = llm_judge(c["criterion"], deliverable_text, final_prompt, args.judge_model)
            mode = "judge"
        total_w += w
        total_ws += w * score
        by_cat.setdefault(c.get("category", "Uncategorized"), []).append(score)
        results.append({"criterion": c["criterion"], "category": c.get("category"),
                        "weight": w, "mode": mode, "score": round(score, 3), "detail": detail})

    task_score = round(total_ws / total_w, 4) if total_w else 0.0
    cat_scores = {k: round(sum(v) / len(v), 4) for k, v in by_cat.items()}

    out = {
        "task_id": args.task_id,
        "workflow_cat": (task or {}).get("workflow_cat"),
        "product": (task or {}).get("product"),
        "task_score": task_score,
        "by_category": cat_scores,
        "criteria": results,
    }
    if args.cost_usd is not None:
        out["cost_usd"] = args.cost_usd  # leaderboard.py reads this for the Pareto view
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"{args.task_id}: {task_score}  ->  {args.out}")
    for cat, s in cat_scores.items():
        print(f"   {cat}: {s}")


if __name__ == "__main__":
    main()
