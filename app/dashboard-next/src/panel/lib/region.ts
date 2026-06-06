/** True when a node region preset marks an in-country (Iran) server. */
export const isIranNode = (region?: string | null) => {
  const r = (region || "").toLowerCase();
  return r === "ir" || r === "iran" || r === "domestic" || r.startsWith("ir-");
};
