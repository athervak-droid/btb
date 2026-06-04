import board from "../data/leaderboard.json";
import CostAccuracyScatter from "./CostAccuracyScatter";

export default function Page() {
  const rows = board.leaderboard ?? [];
  const pareto = board.pareto ?? [];

  // union of all categories seen, stable-sorted, for the per-category columns
  const categories = Array.from(
    new Set(rows.flatMap((r) => Object.keys(r.by_category ?? {})))
  ).sort();

  const pct = (x) => (x == null ? "-" : `${(x * 100).toFixed(1)}%`);
  const topAcc = Math.max(1e-9, ...rows.map((r) => r.overall ?? 0));

  return (
    <main>
      <div className="header">
        <h1>BankerToolBench Leaderboard</h1>
        <p>AI agents on real investment-banking deliverables, scored against expert rubrics.</p>
      </div>

      <div className="section-title">Overall</div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th className="rank">#</th>
              <th>Model</th>
              <th className="num">Overall</th>
              {categories.map((c) => (
                <th key={c} className="num">{c}</th>
              ))}
              <th className="num">Tasks</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.model}>
                <td className="rank">{i + 1}</td>
                <td className="model">{r.model}</td>
                <td className="num">
                  <div className="bar-wrap">
                    <div className="bar-track">
                      <div className="bar-fill"
                           style={{ width: `${((r.overall ?? 0) / topAcc) * 100}%` }} />
                    </div>
                    <span>{pct(r.overall)}</span>
                  </div>
                </td>
                {categories.map((c) => (
                  <td key={c} className="num">{pct(r.by_category?.[c])}</td>
                ))}
                <td className="num">{r.n_tasks}</td>
                <td className="num">${(r.total_cost_usd ?? 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-title">Cost vs. Accuracy</div>
      <div className="panel chart-card">
        <CostAccuracyScatter points={pareto} />
      </div>

      <p className="foot">
        Scores are the weighted mean across rubric criteria, per task and averaged
        for the headline. Refresh the data with{" "}
        <code>python scripts/leaderboard.py --results results/ --out results/leaderboard.json</code>{" "}
        then <code>npm run sync</code> in <code>web/</code>.
      </p>
    </main>
  );
}
