"use client";

import {
  ResponsiveContainer, ScatterChart, Scatter, XAxis, YAxis,
  CartesianGrid, Tooltip, LabelList, ZAxis,
} from "recharts";

const AXIS = "#6b7384";
const GRID = "#1e2430";

function PointTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{
      background: "#171b24", border: "1px solid #2c3340", borderRadius: 10,
      padding: "9px 13px", fontSize: 13, color: "#e8eaed",
      boxShadow: "0 8px 24px -8px rgba(0,0,0,0.7)",
    }}>
      <div style={{ fontWeight: 700, marginBottom: 3 }}>{p.model}</div>
      <div style={{ color: "#9aa3b2" }}>{(p.accuracy * 100).toFixed(1)}% accuracy</div>
      <div style={{ color: "#9aa3b2" }}>${p.cost_usd.toFixed(2)} total cost</div>
    </div>
  );
}

export default function CostAccuracyScatter({ points, frontier = [] }) {
  const data = points.map((p) => ({ ...p, accuracyPct: p.accuracy * 100 }));
  const front = data
    .filter((p) => frontier.includes(p.model))
    .sort((a, b) => a.cost_usd - b.cost_usd);

  return (
    <div style={{ width: "100%", height: 380 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 18, right: 30, bottom: 38, left: 6 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis
            type="number" dataKey="cost_usd" name="Cost"
            tick={{ fill: AXIS, fontSize: 12 }} stroke={GRID}
            tickFormatter={(v) => `$${v.toFixed(0)}`}
            label={{ value: "Total cost across all tasks (USD)", position: "bottom",
                     offset: 20, fill: AXIS, fontSize: 12 }}
          />
          <YAxis
            type="number" dataKey="accuracyPct" name="Accuracy"
            domain={[50, 95]} tick={{ fill: AXIS, fontSize: 12 }} stroke={GRID}
            tickFormatter={(v) => `${v}%`}
            label={{ value: "Accuracy", angle: -90, position: "insideLeft",
                     fill: AXIS, fontSize: 12, dy: 26 }}
          />
          <ZAxis range={[150, 150]} />
          <Tooltip content={<PointTooltip />} cursor={{ stroke: GRID }} />
          {/* Pareto frontier line (drawn first, behind points) */}
          <Scatter data={front} fill="#34d399" line={{ stroke: "#34d399", strokeWidth: 2, strokeDasharray: "5 4" }}
                   shape="circle" isAnimationActive={false} legendType="none" />
          {/* all models */}
          <Scatter data={data} fill="#6ea8fe" isAnimationActive={false}>
            <LabelList dataKey="model" position="top"
                       style={{ fill: "#cdd3df", fontSize: 11, fontWeight: 600 }} />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
