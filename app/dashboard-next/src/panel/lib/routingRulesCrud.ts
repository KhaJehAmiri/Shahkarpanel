/** Granular routing-rule CRUD — wraps /core/routing/rules API (not bulk PUT /core/config). */
import { api } from "../api/client";
import { shapeCoreConfig } from "./outboundCrud";

export type RoutingRulesList = {
  rules: Record<string, unknown>[];
  domainStrategy?: string;
};

export async function fetchRoutingRules(): Promise<RoutingRulesList> {
  return api.get<RoutingRulesList>("/core/routing/rules");
}

export async function addRoutingRule(
  rule: Record<string, unknown>,
  index?: number,
): Promise<Record<string, unknown>> {
  const saved = await api.post<Record<string, unknown>>("/core/routing/rules", { rule, index });
  return shapeCoreConfig(saved);
}

export async function replaceRoutingRules(
  rules: Record<string, unknown>[],
): Promise<Record<string, unknown>> {
  const saved = await api.put<Record<string, unknown>>("/core/routing/rules", { rules });
  return shapeCoreConfig(saved);
}

export async function updateRoutingRule(
  index: number,
  rule: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const saved = await api.put<Record<string, unknown>>(`/core/routing/rules/${index}`, { rule });
  return shapeCoreConfig(saved);
}

export async function deleteRoutingRule(index: number): Promise<Record<string, unknown>> {
  const saved = await api.del<Record<string, unknown>>(`/core/routing/rules/${index}`);
  return shapeCoreConfig(saved);
}

export async function patchRoutingMeta(
  patch: { domainStrategy?: string },
): Promise<Record<string, unknown>> {
  const saved = await api.patch<Record<string, unknown>>("/core/routing", patch);
  return shapeCoreConfig(saved);
}
