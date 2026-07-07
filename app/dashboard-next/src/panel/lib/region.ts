/** True when a node region preset marks an in-country (Iran) server. */
export const isIranNode = (region?: string | null) => {
  const r = (region || "").toLowerCase();
  return r === "ir" || r === "iran" || r === "domestic" || r.startsWith("ir-");
};

/** Match a template region preset (IR, DE, NL, …) against a node region label. */
export const regionMatches = (preset?: string | null, nodeRegion?: string | null) => {
  if (!preset || !nodeRegion) return false;
  const p = preset.toUpperCase();
  if (p === "IR") return isIranNode(nodeRegion);
  const r = nodeRegion.toUpperCase();
  return r === p || r.startsWith(`${p}-`);
};

export const pickNodeByRegion = <T extends { id: number; region?: string | null }>(
  nodes: T[],
  preset?: string | null,
): T | undefined => {
  if (!preset) return undefined;
  return nodes.find((n) => regionMatches(preset, n.region));
};
