"""Aggregate per-task result files into a leaderboard.

Reads results/*.json (each written by eval/score.py, named <model>__<task>.json),
and produces an overall score per model, a per-workflow-category breakdown, and
cost-vs-accuracy (Pareto) points if cost/tokens were recorded.

Usage:
    python scripts/leaderboard.py --results results/ --out results/leaderboard.json
"""
from __future__ import annotations
import argparse
import glob
import json
import os
from collections import defaultdict


def model_from_filename(path: str) -> str:
    base = os.path.basename(path).rsplit(".", 1)[0]
    return base.split("__", 1)[0] if "__" in base else "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="results/leaderboard.json")
    args = ap.parse_args()

    per_model_scores = defaultdict(list)
    per_model_cat = defaultdict(lambda: defaultdict(list))
    per_model_prod = defaultdict(lambda: defaultdict(list))
    per_model_cost = defaultdict(float)

    for path in glob.glob(os.path.join(args.results, "*.json")):
        if os.path.basename(path) == "leaderboard.json":
            continue
        with open(path) as f:
            r = json.load(f)
        if "task_score" not in r:
            continue
        model = model_from_filename(path)
        per_model_scores[model].append(r["task_score"])
        cat = r.get("workflow_cat") or "Uncategorized"
        per_model_cat[model][cat].append(r["task_score"])
        if r.get("product"):
            per_model_prod[model][r["product"]].append(r["task_score"])
        per_model_cost[model] += float(r.get("cost_usd", 0) or 0)

    board = []
    for model, scores in per_model_scores.items():
        overall = sum(scores) / len(scores)
        cats = {c: round(sum(v) / len(v), 4) for c, v in per_model_cat[model].items()}
        prods = {p: round(sum(v) / len(v), 4) for p, v in per_model_prod[model].items()}
        cost = round(per_model_cost[model], 2)
        board.append({
            "model": model,
            "overall": round(overall, 4),
            "n_tasks": len(scores),
            "by_category": cats,
            "by_product": prods,
            "total_cost_usd": cost,
            "avg_cost_usd": round(cost / len(scores), 3) if scores else 0,
        })
    board.sort(key=lambda x: x["overall"], reverse=True)

    pareto = [{"model": b["model"], "accuracy": b["overall"], "cost_usd": b["total_cost_usd"]}
              for b in board]

    out = {"leaderboard": board, "pareto": pareto}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    # markdown table for quick eyeballing / pasting into a README
    print(f"{'Model':<28} {'Overall':>8} {'Tasks':>6} {'Cost $':>8}")
    print("-" * 54)
    for b in board:
        print(f"{b['model']:<28} {b['overall']*100:>7.1f}% {b['n_tasks']:>6} {b['total_cost_usd']:>8.2f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
