// Categorical palette, validated for this app's dark surface (Tailwind
// slate-900, #0f172a) via the dataviz skill's validate_palette.js — 8-slot
// fixed hue order (never cycled/reassigned; a series always keeps its slot).
export const CATEGORICAL_COLORS = [
  "#3987e5", // blue
  "#199e70", // aqua
  "#c98500", // yellow
  "#008300", // green
  "#9085e9", // violet
  "#e66767", // red
  "#d55181", // magenta
  "#d95926", // orange
] as const;
