import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../../api/client";
import { SourceFilter } from "./SourceFilter";

export function DashboardPage() {
  const pricesQuery = useQuery({
    queryKey: ["day-ahead-prices"],
    queryFn: () => api.dayAheadPrices(),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-6">
      <SourceFilter />
      <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-4 text-sm font-medium text-slate-400">Day-ahead price</h2>
        {pricesQuery.isLoading && <p className="text-slate-500">Loading…</p>}
        {pricesQuery.isError && <p className="text-red-400">Failed to load prices.</p>}
        {pricesQuery.data && pricesQuery.data.length === 0 && (
          <p className="text-slate-500">
            No data yet — the backend's background refresh job hasn't populated the warehouse.
          </p>
        )}
        {pricesQuery.data && pricesQuery.data.length > 0 && (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={pricesQuery.data}>
              <XAxis dataKey="timestamp" hide />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="price_per_mwh" stroke="#38bdf8" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>
    </div>
  );
}
