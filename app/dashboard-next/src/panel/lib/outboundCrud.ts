/** Granular outbound CRUD — wraps /core/outbounds API (not bulk PUT /core/config). */
import { api } from "../api/client";
import { ensureConfigShape, sanitizeConfigOutbounds } from "./xrayHelpers";

export function shapeCoreConfig(raw: Record<string, unknown>): Record<string, unknown> {
  return sanitizeConfigOutbounds(ensureConfigShape(raw));
}

export async function fetchCoreConfig(): Promise<Record<string, unknown>> {
  const data = await api.get<Record<string, unknown>>("/core/config");
  return shapeCoreConfig(data);
}

export async function createOutbound(outbound: Record<string, unknown>): Promise<Record<string, unknown>> {
  const saved = await api.post<Record<string, unknown>>("/core/outbounds", { outbound });
  return shapeCoreConfig(saved);
}

export async function replaceOutbound(
  tag: string,
  outbound: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const newTag = String(outbound.tag || tag);
  if (newTag === tag) {
    const saved = await api.put<Record<string, unknown>>(
      `/core/outbounds/${encodeURIComponent(tag)}`,
      { outbound },
    );
    return shapeCoreConfig(saved);
  }
  await api.del(`/core/outbounds/${encodeURIComponent(tag)}`);
  const saved = await api.post<Record<string, unknown>>("/core/outbounds", { outbound });
  return shapeCoreConfig(saved);
}

export async function removeOutbound(tag: string): Promise<Record<string, unknown>> {
  const saved = await api.del<Record<string, unknown>>(`/core/outbounds/${encodeURIComponent(tag)}`);
  return shapeCoreConfig(saved);
}

export async function reorderOutbounds(
  outbounds: Record<string, unknown>[],
): Promise<Record<string, unknown>> {
  const saved = await api.put<Record<string, unknown>>("/core/outbounds", { outbounds });
  return shapeCoreConfig(saved);
}

export async function upsertOutbound(
  outbound: Record<string, unknown>,
  existingTags: Set<string>,
): Promise<Record<string, unknown>> {
  const tag = String(outbound.tag || "");
  if (existingTags.has(tag)) {
    return replaceOutbound(tag, outbound);
  }
  return createOutbound(outbound);
}
