import { useCallback, useState } from "react";
import { api } from "../../api/client";
import { ensureConfigShape, SHAHKAR_INBOUND_KIND, sanitizeConfigOutbounds } from "../../lib/xrayHelpers";

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

async function prepareConfigForSave(config: Record<string, unknown>): Promise<Record<string, unknown>> {
  const shaped = sanitizeConfigOutbounds(ensureConfigShape(cloneJson(config)));
  const inbounds = [...((shaped.inbounds || []) as Record<string, unknown>[])];
  let changed = false;

  for (let i = 0; i < inbounds.length; i++) {
    const ib = { ...inbounds[i] };
    const proto = String(ib.protocol || "").toLowerCase();
    if (proto !== "wireguard" && proto !== "amneziawg") continue;

    const wasAmnezia = proto === "amneziawg"
      || (ib.settings as Record<string, unknown> | undefined)?.[SHAHKAR_INBOUND_KIND] === "amneziawg";

    ib.protocol = "wireguard";
    if (ib.streamSettings) {
      delete ib.streamSettings;
      changed = true;
    }
    if (ib.sniffing) {
      delete ib.sniffing;
      changed = true;
    }

    const settings = { ...((ib.settings || {}) as Record<string, unknown>) };
    delete settings.clients;
    if (!String(settings.secretKey || "").trim()) {
      const kp = await api.get<{ privateKey: string }>("/core/wireguard/keypair");
      settings.secretKey = kp.privateKey;
      changed = true;
    }
    if (!settings.mtu) settings.mtu = 1420;
    if (!Array.isArray(settings.peers)) settings.peers = [];
    if (wasAmnezia) settings[SHAHKAR_INBOUND_KIND] = "amneziawg";
    ib.settings = settings;
    inbounds[i] = ib;
    changed = true;
  }

  return { ...shaped, inbounds };
}

export function useXrayConfig() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<Record<string, unknown>>("/core/config");
      setConfig(sanitizeConfigOutbounds(ensureConfigShape(data)));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }, []);

  const save = useCallback(
    async (next: Record<string, unknown>) => {
      setSaving(true);
      try {
        const shaped = await prepareConfigForSave(next);
        await api.put("/core/config", shaped);
        setConfig(shaped);
        return true;
      } catch (e: unknown) {
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  const patch = useCallback(
    (fn: (c: Record<string, unknown>) => Record<string, unknown>) => {
      if (!config) return;
      setConfig(fn({ ...config }));
    },
    [config],
  );

  return { config, setConfig, loading, error, saving, reload, save, patch };
}
