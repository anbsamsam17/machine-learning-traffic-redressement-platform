"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface LossPoint {
  epoch: number;
  loss: number;
  val_loss: number;
}

export function LossChart({ data }: { data: LossPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
        <XAxis
          dataKey="epoch"
          tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}
          stroke="var(--color-border)"
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}
          stroke="var(--color-border)"
        />
        <Tooltip
          contentStyle={{
            background: "var(--color-bg-elevated)",
            border: "1px solid var(--color-border)",
            borderRadius: 6,
            fontSize: 11,
            color: "var(--color-text)",
          }}
          labelStyle={{ color: "var(--color-text-muted)" }}
        />
        <Line
          type="monotone"
          dataKey="loss"
          stroke="var(--color-chart-1)"
          strokeWidth={1.5}
          dot={false}
          name="Train"
        />
        <Line
          type="monotone"
          dataKey="val_loss"
          stroke="var(--color-chart-2)"
          strokeWidth={1.5}
          dot={false}
          name="Val"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
