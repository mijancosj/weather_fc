import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../../api/client";
import { areaColorIndex, areaLabel, canonicalArea } from "./areas";
import { formatTimestamp } from "./formatTimestamp";
import { GenerationStackChart } from "./GenerationStackChart";
import { OutagesPanel } from "./OutagesPanel";
import { CATEGORICAL_COLORS } from "./palette";
import { SourceFilter } from "./SourceFilter";

export function DashboardPage() {
  const pricesQuery = useQuery({
    queryKey: ["day-ahead-prices"],
    queryFn: () => api.dayAheadPrices(),
    refetchInterval: 60_000,
  });

  const { rows, areas, currencyByArea } = useMemo(() => {
    if (!pricesQuery.data) {
      return { rows: [], areas: [] as string[], currencyByArea: {} as Record<string, string> };
    }

    const byTimestamp = new Map<string, Record<string, number | string>>();
    const areasPresent = new Set<string>();
    const currency: Record<string, string> = {};

    for (const point of pricesQuery.data) {
      const area = canonicalArea(point.area);
      areasPresent.add(area);
      currency[area] = point.currency;

      const row = byTimestamp.get(point.timestamp) ?? { timestamp: point.timestamp };
      row[area] = point.price_per_mwh;
      byTimestamp.set(point.timestamp, row);
    }

    const sortedRows = Array.from(byTimestamp.values()).sort((a, b) =>
      String(a.timestamp).localeCompare(String(b.timestamp)),
    );
    const orderedAreas = Array.from(areasPresent).sort(
      (a, b) => areaColorIndex(a) - areaColorIndex(b),
    );
    return { rows: sortedRows, areas: orderedAreas, currencyByArea: currency };
  }, [pricesQuery.data]);

  return (
    <div className="space-y-6">
      <SourceFilter />
      <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-4 text-sm font-medium text-slate-400">Day-ahead price</h2>
        {pricesQuery.isLoading && <p className="text-slate-500">Loading…</p>}
        {pricesQuery.isError && <p className="text-red-400">Failed to load prices.</p>}
        {pricesQuery.data && rows.length === 0 && (
          <p className="text-slate-500">
            No data yet — the backend's background refresh job hasn't populated the warehouse.
          </p>
        )}
        {rows.length > 0 && (
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={rows} margin={{ bottom: 8 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="timestamp"
                tickFormatter={formatTimestamp}
                stroke="#898781"
                tick={{ fill: "#898781", fontSize: 11 }}
                minTickGap={40}
              />
              <YAxis stroke="#898781" tick={{ fill: "#898781", fontSize: 12 }} />
              <Tooltip
                contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #1e293b" }}
                labelStyle={{ color: "#c3c2b7" }}
                labelFormatter={formatTimestamp}
              />
              <Legend
                wrapperStyle={{ color: "#c3c2b7", fontSize: 12 }}
                formatter={(value: string) =>
                  `${areaLabel(value)} (${currencyByArea[value] ?? "?"})`
                }
              />
              {areas.map((area) => (
                <Line
                  key={area}
                  type="monotone"
                  dataKey={area}
                  name={area}
                  stroke={CATEGORICAL_COLORS[areaColorIndex(area) % CATEGORICAL_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>
      <GenerationStackChart />
      <OutagesPanel />
    </div>
  );
}
