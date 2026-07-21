// Prices/observations store area two different ways depending on source:
// entsoe rows use the full ENTSO-E EIC bidding-zone code (e.g.
// "10YFR-RTE------C"), while elexon/esios rows use a short code (e.g. "GB").
// This normalizes either to one canonical short code so a country gets one
// consistent color/label regardless of which source reported it.
const EIC_TO_CANONICAL: Record<string, string> = {
  "10YFR-RTE------C": "FR",
  "10YES-REE------0": "ES",
  "10YPT-REN------W": "PT",
  "10YGB----------A": "GB",
  "10Y1001A1001A82H": "DE_LU",
  "10YNL----------L": "NL",
  "10YBE----------2": "BE",
};

export function canonicalArea(area: string): string {
  return EIC_TO_CANONICAL[area] ?? area;
}

export const AREA_NAMES: Record<string, string> = {
  FR: "France",
  ES: "Spain",
  PT: "Portugal",
  GB: "United Kingdom",
  DE_LU: "Germany-Luxembourg",
  NL: "Netherlands",
  BE: "Belgium",
};

export function areaLabel(area: string): string {
  const canonical = canonicalArea(area);
  return AREA_NAMES[canonical] ?? canonical;
}

// Fixed order = fixed color assignment (see palette.ts) — a country keeps
// its color whether or not every country has data in the current window.
// The 4 in-focus markets first, anything else appended after.
export const CANONICAL_AREA_ORDER = ["FR", "ES", "PT", "GB"];

export function areaColorIndex(area: string): number {
  const canonical = canonicalArea(area);
  const index = CANONICAL_AREA_ORDER.indexOf(canonical);
  return index === -1 ? CANONICAL_AREA_ORDER.length : index;
}
