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

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`Request to ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  dayAheadPrices: (params: { source?: string; area?: string } = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined) as [string, string][],
    ).toString();
    return get<PricePoint[]>(`/v1/prices/day-ahead${query ? `?${query}` : ""}`);
  },
  sources: () => get<Source[]>("/v1/sources"),
};
