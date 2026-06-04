"use client";

import {
  ResponsiveContainer, ScatterChart, Scatter, XAxis, YAxis,
  CartesianGrid, Tooltip, LabelList, ZAxis,
} from "recharts";

const AXIS = "#8b93a7";
const GRID = "#262c3a";

function PointTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{
      background: "#1a1f2e", border: "1px solid #262c3a", borderRadius: 8,
      padding: "8px 12px", fontSize: 13, color: "#e6e9ef",
    }}>
      <div style={{ fontWeight: 600, marginBottom: 2 }}>{p.model}</div>
      <div style={{ color: "#8b93a7" }}>{(p.accuracy * 100).toFixed(1)}% accuracy</div>
      <div style={{ color: "#8b93a7" }}>${p.cost_usd.toFixed(2)} cost</div>
    </div>
  );
}

export default function CostAccuracyScatter({ points }) {
  // y as percentage for readability
  const data = points.map((p) => ({ ...p, accuracyPct: p.accuracy * 100 }));
  return (
    <div style={{ width: "100%", height: 340 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 16, right: 28, bottom: 36, left: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis
            type="number" dataKey="cost_usd" name="Cost"
            tick={{ fill: AXIS, fontSize: 12 }} stroke={GRID}
            tickFormatter={(v) => `$${v.toFixed(2)}`}
            label={{ value: "Cost per task run (USD)", position: "bottom",
                     offset: 18, fill: AXIS, fontSize: 12 }}
          />
          <YAxis
            type="number" dataKey="accuracyPct" name="Accuracy"
            domain={[0, 100]} tick={{ fill: AXIS, fontSize: 12 }} stroke={GRID}
            tickFormatter={(v) => `${v}%`}
            label={{ value: "Accuracy", angle: -90, position: "insideLeft",
                     fill: AXIS, fontSize: 12, dy: 30 }}
          />
          <ZAxis range={[120, 120]} />
          <Tooltip content={<PointTooltip />} cursor={{ stroke: GRID }} />
          <Scatter data={data} fill="#5b9dff">
            <LabelList dataKey="model" position="top"
                       style={{ fill: "#e6e9ef", fontSize: 11 }} />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
