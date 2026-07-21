import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../../api/client";
import { AREA_NAMES, CANONICAL_AREA_ORDER, areaLabel } from "./areas";
import { formatTimestamp } from "./formatTimestamp";
import { CATEGORICAL_COLORS } from "./palette";

// ENTSO-E's ~16 production-type codes folded into 8 buckets (one per
// categorical color slot) — a 9th series is never a generated hue, so the
// long tail folds into "Other" instead. See entsoe-retriever's PSR_TYPE_NAMES
// for the full code list this draws from.
const PSR_BUCKETS: Record<string, string> = {
  B01: "Biomass",
  B02: "Coal",
  B03: "Fossil Gas",
  B04: "Fossil Gas",
  B05: "Coal",
  B06: "Other",
  B07: "Other",
  B08: "Other",
  B09: "Other",
  B10: "Hydro",
  B11: "Hydro",
  B12: "Hydro",
  B13: "Other",
  B14: "Nuclear",
  B15: "Other",
  B16: "Solar",
  B17: "Other",
  B18: "Wind",
  B19: "Wind",
  B20: "Other",
  B25: "Other",
};

// Fixed order = fixed color assignment (BUCKET_ORDER.indexOf), so a bucket
// keeps its color whether or not every bucket is present in a given window.
const BUCKET_ORDER = [
  "Wind",
  "Solar",
  "Hydro",
  "Nuclear",
  "Fossil Gas",
  "Coal",
  "Biomass",
  "Other",
];

function bucketFor(indicatorId: string): string | null {
  if (indicatorId.endsWith(":consumption")) return null; // pumping load, not generation
  const psrType = indicatorId.split(":")[1];
  return PSR_BUCKETS[psrType] ?? "Other";
}

export function GenerationStackChart() {
  const [selectedArea, setSelectedArea] = useState<string>(CANONICAL_AREA_ORDER[0]);

  const observationsQuery = useQuery({
    queryKey: ["indicator-observations", "entsoe", selectedArea],
    queryFn: () => api.indicatorObservations({ source: "entsoe", geo_name: selectedArea }),
    refetchInterval: 60_000,
  });

  // ENTSO-E's technologies don't all publish with the same latency: fast
  // ones (wind, solar, some fossil subtypes) land within ~15min, slower ones
  // (biomass, hydro, waste, ...) can lag by hours. Past the slowest
  // technology's last real point, the stack would silently be missing a
  // contributor — reading as a sudden generation collapse rather than a
  // data-freshness gap. Trimming to the common-coverage window keeps the
  // "stack" honest at the cost of a few hours of the most recent data.
  const MIN_POINTS_FOR_COVERAGE = 5;

  const { rows, buckets, trimmedAt } = useMemo(() => {
    if (!observationsQuery.data) {
      return { rows: [], buckets: [] as string[], trimmedAt: null as string | null };
    }

    const byTimestamp = new Map<string, Record<string, number | string>>();
    const bucketsPresent = new Set<string>();
    const coverage = new Map<string, { count: number; maxTimestamp: string }>();

    for (const obs of observationsQuery.data) {
      const bucket = bucketFor(obs.indicator_id);
      if (!bucket) continue;
      bucketsPresent.add(bucket);

      const row = byTimestamp.get(obs.timestamp) ?? { timestamp: obs.timestamp };
      row[bucket] = (Number(row[bucket]) || 0) + obs.value;
      byTimestamp.set(obs.timestamp, row);

      const entry = coverage.get(obs.indicator_id) ?? { count: 0, maxTimestamp: obs.timestamp };
      entry.count += 1;
      if (obs.timestamp > entry.maxTimestamp) entry.maxTimestamp = obs.timestamp;
      coverage.set(obs.indicator_id, entry);
    }

    const fullCoverageMaxTimestamps = Array.from(coverage.values())
      .filter((c) => c.count >= MIN_POINTS_FOR_COVERAGE)
      .map((c) => c.maxTimestamp);
    const cutoff = fullCoverageMaxTimestamps.length
      ? fullCoverageMaxTimestamps.reduce((earliest, ts) => (ts < earliest ? ts : earliest))
      : null;

    const sortedRows = Array.from(byTimestamp.values())
      .filter((row) => !cutoff || String(row.timestamp) <= cutoff)
      .sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
    const orderedBuckets = BUCKET_ORDER.filter((bucket) => bucketsPresent.has(bucket));
    return { rows: sortedRows, buckets: orderedBuckets, trimmedAt: cutoff };
  }, [observationsQuery.data]);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-400">Generation mix (MW)</h2>
        <div className="flex gap-1">
          {CANONICAL_AREA_ORDER.map((area) => (
            <button
              key={area}
              type="button"
              onClick={() => setSelectedArea(area)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                area === selectedArea
                  ? "border-sky-500 bg-sky-500/10 text-sky-300"
                  : "border-slate-700 text-slate-400 hover:border-slate-500"
              }`}
            >
              {AREA_NAMES[area]}
            </button>
          ))}
        </div>
      </div>
      {observationsQuery.isLoading && <p className="text-slate-500">Loading…</p>}
      {observationsQuery.isError && (
        <p className="text-red-400">Failed to load generation data.</p>
      )}
      {observationsQuery.data && rows.length === 0 && (
        <p className="text-slate-500">
          No generation data for {areaLabel(selectedArea)} yet.{" "}
          {selectedArea === "GB"
            ? "ENTSO-E doesn't publish generation-by-type for the UK post-Brexit — this would need a UK-specific source (Elexon only covers prices here so far)."
            : "The backend's ENTSO-E generation refresh hasn't run yet."}
        </p>
      )}
      {trimmedAt && (
        <p className="mb-2 text-xs text-slate-500">
          Trimmed to {trimmedAt.replace("T", " ").slice(0, 16)} UTC — some technologies (biomass,
          hydro, waste, ...) publish with more delay than others (wind, solar); showing the full
          range would understate the total for whichever hasn't reported yet.
        </p>
      )}
      {rows.length > 0 && (
        <ResponsiveContainer width="100%" height={360}>
          <AreaChart data={rows} margin={{ bottom: 8 }}>
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
            <Legend wrapperStyle={{ color: "#c3c2b7", fontSize: 12 }} />
            {buckets.map((bucket) => (
              <Area
                key={bucket}
                type="monotone"
                dataKey={bucket}
                stackId="generation"
                name={bucket}
                stroke={CATEGORICAL_COLORS[BUCKET_ORDER.indexOf(bucket)]}
                fill={CATEGORICAL_COLORS[BUCKET_ORDER.indexOf(bucket)]}
                fillOpacity={0.75}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}
