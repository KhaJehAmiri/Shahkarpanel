import { useCallback, useState } from "react";
import { api } from "../../api/client";
import { ensureConfigShape } from "../../lib/xrayHelpers";

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
      setConfig(ensureConfigShape(data));
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
        const shaped = ensureConfigShape(next);
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
