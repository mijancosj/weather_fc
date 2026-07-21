import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, type Outage } from "../../api/client";
import { AREA_NAMES, CANONICAL_AREA_ORDER, areaLabel } from "./areas";

// See entsoe-retriever's OUTAGE_BUSINESS_TYPE_NAMES for the source of truth —
// duplicated here rather than fetched since it's a tiny, effectively-static
// code table (only two values ever confirmed live: planned vs. forced).
const BUSINESS_TYPE_LABELS: Record<string, string> = {
  A53: "Planned maintenance",
  A54: "Forced unavailability",
};

const RESOURCE_TYPE_FILTERS = ["all", "generation", "transmission"] as const;
type ResourceTypeFilter = (typeof RESOURCE_TYPE_FILTERS)[number];

const AREA_EIC: Record<string, string> = {
  FR: "10YFR-RTE------C",
  ES: "10YES-REE------0",
  PT: "10YPT-REN------W",
  GB: "10YGB----------A",
};

type Status = "active" | "upcoming" | "ended";

function statusOf(outage: Outage, now: Date): Status {
  const start = new Date(outage.period_start);
  const end = new Date(outage.period_end);
  if (now < start) return "upcoming";
  if (now > end) return "ended";
  return "active";
}

const STATUS_STYLE: Record<Status, { dot: string; label: string }> = {
  active: { dot: "bg-amber-500", label: "Active" },
  upcoming: { dot: "bg-sky-500", label: "Upcoming" },
  ended: { dot: "bg-slate-600", label: "Ended" },
};

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function capacityImpact(outage: Outage): string {
  if (outage.resource_type === "generation") {
    const { nominal_capacity_mw, min_available_capacity_mw } = outage;
    if (nominal_capacity_mw != null && min_available_capacity_mw != null) {
      const lost = nominal_capacity_mw - min_available_capacity_mw;
      return `-${lost.toFixed(0)} MW (of ${nominal_capacity_mw.toFixed(0)} MW)`;
    }
    return "—";
  }
  const { min_available_capacity_mw, max_available_capacity_mw } = outage;
  if (min_available_capacity_mw != null && max_available_capacity_mw != null) {
    if (min_available_capacity_mw === max_available_capacity_mw) {
      return `${min_available_capacity_mw.toFixed(0)} MW available`;
    }
    return `${min_available_capacity_mw.toFixed(0)}–${max_available_capacity_mw.toFixed(0)} MW available`;
  }
  return "—";
}

function whatOrBorder(outage: Outage): string {
  if (outage.resource_type === "generation") {
    return outage.unit_name ?? outage.unit_id ?? "Unknown unit";
  }
  const inLabel = outage.in_area ? areaLabel(outage.in_area) : "?";
  const outLabel = outage.out_area ? areaLabel(outage.out_area) : "?";
  return `${inLabel} ↔ ${outLabel}`;
}

export function OutagesPanel() {
  const [resourceType, setResourceType] = useState<ResourceTypeFilter>("all");
  const [area, setArea] = useState<string | null>(null);
  // Defaults to on: outages are announced months in advance and a trader
  // mostly cares what's out right now, not the full multi-hundred-row
  // history — "Active only" off is an explicit opt-in to see everything.
  const [activeOnly, setActiveOnly] = useState(true);

  const outagesQuery = useQuery({
    queryKey: ["outages", resourceType, area, activeOnly],
    queryFn: () =>
      api.outages({
        resource_type: resourceType === "all" ? undefined : resourceType,
        area: area ? AREA_EIC[area] : undefined,
        active_only: activeOnly ? "true" : undefined,
      }),
    refetchInterval: 60_000,
  });

  const now = useMemo(() => new Date(), [outagesQuery.dataUpdatedAt]);
  const rows = outagesQuery.data ?? [];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-slate-400">
          Outages — planned &amp; forced unavailability
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {RESOURCE_TYPE_FILTERS.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setResourceType(type)}
                className={`rounded-full border px-3 py-1 text-xs capitalize transition-colors ${
                  type === resourceType
                    ? "border-sky-500 bg-sky-500/10 text-sky-300"
                    : "border-slate-700 text-slate-400 hover:border-slate-500"
                }`}
              >
                {type}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setArea(null)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                area === null
                  ? "border-sky-500 bg-sky-500/10 text-sky-300"
                  : "border-slate-700 text-slate-400 hover:border-slate-500"
              }`}
            >
              All areas
            </button>
            {CANONICAL_AREA_ORDER.filter((a) => a !== "GB").map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => setArea(a)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  area === a
                    ? "border-sky-500 bg-sky-500/10 text-sky-300"
                    : "border-slate-700 text-slate-400 hover:border-slate-500"
                }`}
              >
                {AREA_NAMES[a]}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(event) => setActiveOnly(event.target.checked)}
              className="accent-sky-500"
            />
            Active only
          </label>
        </div>
      </div>

      {outagesQuery.isLoading && <p className="text-slate-500">Loading…</p>}
      {outagesQuery.isError && <p className="text-red-400">Failed to load outages.</p>}
      {outagesQuery.data && rows.length === 0 && (
        <p className="text-slate-500">
          No outages match this filter. GB is excluded — ENTSO-E has no outage data for the UK
          post-Brexit, same as prices and generation.
        </p>
      )}
      {rows.length > 0 && (
        <div className="max-h-96 overflow-y-auto overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900 text-slate-500">
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">Status</th>
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">Area</th>
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">Unit / Border</th>
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">Reason</th>
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">Impact</th>
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">Start</th>
                <th className="sticky top-0 bg-slate-900 py-2 pr-3 font-medium">End</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((outage) => {
                const status = statusOf(outage, now);
                const style = STATUS_STYLE[status];
                return (
                  <tr
                    key={`${outage.event_id}-${outage.revision_number}`}
                    className="border-b border-slate-800/60 text-slate-300"
                  >
                    <td className="py-2 pr-3">
                      <span className="flex items-center gap-1.5">
                        <span className={`h-2 w-2 rounded-full ${style.dot}`} />
                        {style.label}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      {outage.area ? areaLabel(outage.area) : "—"}
                    </td>
                    <td className="py-2 pr-3">{whatOrBorder(outage)}</td>
                    <td className="py-2 pr-3 text-slate-400">
                      {BUSINESS_TYPE_LABELS[outage.business_type] ?? outage.business_type}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{capacityImpact(outage)}</td>
                    <td className="py-2 pr-3 tabular-nums">
                      {formatDateTime(outage.period_start)}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">
                      {formatDateTime(outage.period_end)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
