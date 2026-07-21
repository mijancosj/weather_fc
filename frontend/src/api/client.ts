export interface PricePoint {
  source: string;
  area: string;
  timestamp: string;
  price_per_mwh: number;
  currency: string;
}

export interface Source {
  id: string;
  name: string;
  region: string;
  currency: string;
}

export interface IndicatorObservation {
  source: string;
  indicator_id: string;
  indicator_name: string | null;
  geo_id: number;
  geo_name: string | null;
  timestamp: string;
  value: number;
  unit: string | null;
}

export interface Outage {
  event_id: string;
  revision_number: number;
  resource_type: "generation" | "transmission";
  business_type: string;
  reason_code: string | null;
  area: string | null;
  in_area: string | null;
  out_area: string | null;
  unit_id: string | null;
  unit_name: string | null;
  location_name: string | null;
  psr_type: string | null;
  nominal_capacity_mw: number | null;
  min_available_capacity_mw: number | null;
  max_available_capacity_mw: number | null;
  period_start: string;
  period_end: string;
}

// Empty in dev — relative /api paths go through the Vite proxy
// (vite.config.ts) to localhost:8000. Set for a production build where the
// frontend and backend are on different origins (e.g. Vercel + Render) —
// then this is an absolute URL and the backend's CORS_ORIGINS must include
// this frontend's origin.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api${path}`);
  if (!response.ok) {
    throw new Error(`Request to ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function toQuery(params: Record<string, string | undefined>): string {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined) as [string, string][],
  ).toString();
  return query ? `?${query}` : "";
}

export const api = {
  dayAheadPrices: (params: { source?: string; area?: string } = {}) =>
    get<PricePoint[]>(`/v1/prices/day-ahead${toQuery(params)}`),
  sources: () => get<Source[]>("/v1/sources"),
  indicatorObservations: (
    params: { source?: string; indicator_id?: string; geo_name?: string } = {},
  ) => get<IndicatorObservation[]>(`/v1/indicators/observations${toQuery(params)}`),
  outages: (
    params: { resource_type?: string; area?: string; active_only?: string } = {},
  ) => get<Outage[]>(`/v1/outages${toQuery(params)}`),
};
