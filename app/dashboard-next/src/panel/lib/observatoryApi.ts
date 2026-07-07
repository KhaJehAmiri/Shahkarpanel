/** Observatory / burstObservatory — wraps GET/PUT /core/observatory. */
import { api } from "../api/client";
import { ensureConfigShape, sanitizeConfigOutbounds } from "./xrayHelpers";

export type ObservatoryPayload = {
  observatory?: Record<string, unknown> | null;
  burstObservatory?: Record<string, unknown> | null;
};

export async function fetchObservatory(): Promise<ObservatoryPayload> {
  return api.get<ObservatoryPayload>("/core/observatory");
}

export async function saveObservatory(payload: ObservatoryPayload): Promise<Record<string, unknown>> {
  const saved = await api.put<Record<string, unknown>>("/core/observatory", payload);
  return sanitizeConfigOutbounds(ensureConfigShape(saved));
}

export const DEFAULT_OBSERVATORY: Record<string, unknown> = {
  subjectSelector: [],
  probeUrl: "https://www.google.com/generate_204",
  probeInterval: "10s",
  enableConcurrency: true,
};

export const DEFAULT_BURST_OBSERVATORY: Record<string, unknown> = {
  subjectSelector: [],
  pingConfig: {
    destination: "https://www.google.com/generate_204",
    interval: "1s",
    connectivity: "",
    timeout: "5s",
    samplingCount: 1,
  },
};
