import board from "../data/leaderboard.json";
import CostAccuracyScatter from "./CostAccuracyScatter";

const PRODUCTS = ["M&A", "DCM", "ECM", "LevFin", "Restructuring"];
const MEDALS = ["🥇", "🥈", "🥉"];

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

// score -> heatmap color (red .50 -> amber .70 -> green .90)
function heatColor(s) {
  if (s == null) return "transparent";
  const clamp = (v) => Math.max(0, Math.min(1, v));
  const t = clamp((s - 0.5) / 0.4); // 0 at .50, 1 at .90
  const stops =
    t < 0.5
      ? mix([248, 113, 113], [251, 191, 36], t / 0.5)
      : mix([251, 191, 36], [52, 211, 153], (t - 0.5) / 0.5);
  return `rgba(${stops[0]}, ${stops[1]}, ${stops[2]}, 0.85)`;
}
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

// Pareto frontier: models not dominated on (lower cost, higher accuracy)
function paretoSet(rows) {
  const s = new Set();
  for (const r of rows) {
    const dominated = rows.some(
      (o) => o !== r && o.total_cost_usd <= r.total_cost_usd && o.overall >= r.overall &&
             (o.total_cost_usd < r.total_cost_usd || o.overall > r.overall)
    );
    if (!dominated) s.add(r.model);
  }
  return s;
}

export default function Page() {
  const rows = board.leaderboard ?? [];
  const pareto = board.pareto ?? [];
  const onFrontier = paretoSet(rows);
  const nTasks = rows[0]?.n_tasks ?? 0;
  const topCost = Math.max(...rows.map((r) => r.total_cost_usd || 0), 1);

  return (
    <main>
      <div className="eyebrow">Investment Banking Agent Benchmark</div>
      <h1 className="title">BankerToolBench</h1>
      <p className="subtitle">
        How well AI agents do real investment-banking work — building Excel, PowerPoint,
        and Word deliverables from terse prompts, graded against expert rubrics.
      </p>

      <div className="chips">
        <span className="chip"><span className="dot" /> <b>{rows.length}</b>&nbsp;models</span>
        <span className="chip"><span className="dot" /> <b>{nTasks}</b>&nbsp;tasks</span>
        <span className="chip"><span className="dot" /> <b>{PRODUCTS.length}</b>&nbsp;products</span>
        <span className="chip"><span className="dot" /> M&A · DCM · ECM · LevFin · Restructuring</span>
      </div>
      <div><span className="badge live">Live eval · real agent rollouts graded against expert rubrics · tasks T-002–T-010 (T-001 omitted) · see notes ↓</span></div>

      <div className="section-head">
        <div className="section-title">Leaderboard</div>
        <div className="section-sub">weighted rubric score across {nTasks} tasks</div>
      </div>
      <div className="panel">
        <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th className="rank">#</th>
              <th>Model</th>
              <th style={{ width: "46%" }}>Accuracy</th>
              <th className="right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.model}>
                <td className="rank">
                  {i < 3 ? <span className="medal">{MEDALS[i]}</span> : i + 1}
                </td>
                <td>
                  <span className="model">{r.model}</span>
                  {onFrontier.has(r.model) && <span className="tag">Pareto</span>}
                </td>
                <td>
                  <div className="acc">
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${(r.overall ?? 0) * 100}%` }} />
                    </div>
                    <span className="val">{pct(r.overall)}</span>
                  </div>
                </td>
                <td className="right cost tnum">
                  ${r.total_cost_usd?.toFixed(2)}
                  <span className="per">${(r.avg_cost_usd ?? 0).toFixed(2)}/task</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      <div className="section-head">
        <div className="section-title">Performance by product</div>
        <div className="section-sub">score per IB product line · green is stronger</div>
      </div>
      <div className="panel heatmap">
        <div className="hm-row hm-head">
          <div className="hm-model" />
          {PRODUCTS.map((p) => <div key={p} className="hm-cell hm-label">{p}</div>)}
        </div>
        {rows.map((r) => (
          <div className="hm-row" key={r.model}>
            <div className="hm-model">{r.model}</div>
            {PRODUCTS.map((p) => {
              const s = r.by_product?.[p];
              return (
                <div key={p} className="hm-cell"
                     style={{ background: heatColor(s), color: s == null ? "var(--faint)" : "#0a0c10" }}>
                  {s == null ? "—" : Math.round(s * 100)}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="section-head">
        <div className="section-title">Cost vs. Accuracy</div>
        <div className="section-sub">the frontier is best accuracy per dollar</div>
      </div>
      <div className="panel chart-card">
        <div className="legend">
          <span><span className="sw" style={{ background: "#6ea8fe" }} /> model</span>
          <span><span className="ln" style={{ background: "#34d399" }} /> Pareto frontier</span>
        </div>
        <CostAccuracyScatter points={pareto} frontier={[...onFrontier]} />
      </div>

      <div className="notes">
        <div className="notes-title">Run notes (read before comparing)</div>
        <ul>
          <li><b>gpt-5.5</b> — complete (9/9 tasks). Clean result.</li>
          <li><b>claude-opus-4.8</b> — 7/9 tasks. It over-engineers data-heavy tasks
            (millions of tokens each), which exhausted the gateway's spend cap before
            T-009/T-010 could be graded. Its cost (~$215) reflects that.</li>
          <li><b>gemini-3.5-flash</b> — score is <i>not</i> a fair measure of ability:
            a harness/gateway bug (a 400 "tool call and no content" error) crashed it
            mid-task on most tasks, so it produced no deliverable and scored 0 there.
            It scored ~0.7 on the tasks where it didn't hit that bug.</li>
        </ul>
      </div>

      <p className="foot">
        Each task is scored as the weighted mean across rubric criteria (deterministic checks +
        an LLM judge), averaged for the headline and broken out by product. Per-model task counts
        differ (see notes); the table shows each model's average over the tasks it completed.{" "}
        <a href="https://github.com/athervak-droid/btb">Source on GitHub →</a>
      </p>
    </main>
  );
}
