import { ChangeEvent, FC, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import { useFetch } from "../../lib/useFetch";
import { Button, Callout, Field, Input, Modal, Select, useToast } from "../ui";

type UpstreamRow = {
  address: string;
  port: string;
  user: string;
  pass: string;
};

type OutboundPresetMeta = {
  label?: string;
  description?: string;
  protocol?: string;
  default_balancer_tag?: string;
  default_tag_prefix?: string;
  default_strategy?: string;
  strategies?: string[];
  outbounds?: { settings?: { servers?: { address?: string; port?: number }[] } }[];
};

type PresetsResponse = {
  presets: Record<string, OutboundPresetMeta>;
};

type ApplyResponse = {
  config: Record<string, unknown>;
  applied: {
    preset_id: string;
    outbound_tags: string[];
    balancer_tag: string;
    observatory: boolean;
  };
};

const emptyRow = (sample?: { address?: string; port?: number }): UpstreamRow => ({
  address: sample?.address || "",
  port: sample?.port != null ? String(sample.port) : "",
  user: "",
  pass: "",
});

export const OutboundPoolDialog: FC<{
  onClose: () => void;
  onApplied: (config: Record<string, unknown>) => void;
}> = ({ onClose, onApplied }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const presets = useFetch<PresetsResponse>(() => api.get("/core/outbound-presets"), []);
  const presetIds = useMemo(
    () => Object.keys(presets.data?.presets || {}),
    [presets.data],
  );

  const [presetId, setPresetId] = useState("socks-pool-failover");
  const [balancerTag, setBalancerTag] = useState("socks-pool");
  const [strategy, setStrategy] = useState("leastPing");
  const [enableObservatory, setEnableObservatory] = useState(true);
  const [addRoutingRule, setAddRoutingRule] = useState(false);
  const [rows, setRows] = useState<UpstreamRow[]>([
    emptyRow({ address: "127.0.0.1", port: 1080 }),
    emptyRow({ address: "127.0.0.1", port: 1081 }),
  ]);
  const [busy, setBusy] = useState(false);

  const meta = presets.data?.presets?.[presetId];

  const selectPreset = (id: string) => {
    setPresetId(id);
    const p = presets.data?.presets?.[id];
    if (!p) return;
    setBalancerTag(p.default_balancer_tag || "upstream-pool");
    setStrategy(p.default_strategy || "leastPing");
    setEnableObservatory((p.default_strategy || "") === "leastPing");
    const samples = (p.outbounds || [])
      .map((o) => o.settings?.servers?.[0])
      .filter(Boolean) as { address?: string; port?: number }[];
    if (samples.length) {
      setRows(samples.map((s) => emptyRow(s)));
    } else {
      setRows([emptyRow(), emptyRow()]);
    }
  };

  const updateRow = (idx: number, patch: Partial<UpstreamRow>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => setRows((prev) => [...prev, emptyRow()]);
  const removeRow = (idx: number) => {
    if (rows.length <= 1) return;
    setRows((prev) => prev.filter((_, i) => i !== idx));
  };

  const strategies = meta?.strategies || ["leastPing", "random", "roundRobin"];

  const apply = async () => {
    const upstreams = rows
      .map((r) => ({
        address: r.address.trim(),
        port: parseInt(r.port, 10),
        user: r.user.trim() || undefined,
        pass: r.pass.trim() || undefined,
      }))
      .filter((u) => u.address);

    if (!upstreams.length) {
      toast.push(t("outboundPool.upstreamRequired"), "error");
      return;
    }

    setBusy(true);
    try {
      const res = await api.post<ApplyResponse>(
        `/core/outbound-presets/${encodeURIComponent(presetId)}/apply`,
        {
          upstreams,
          balancer_tag: balancerTag.trim(),
          strategy,
          enable_observatory: enableObservatory,
          add_routing_rule: addRoutingRule,
          replace_existing: true,
        },
      );
      onApplied(res.config);
      toast.push(
        t("outboundPool.applied", {
          tag: res.applied.balancer_tag,
          count: res.applied.outbound_tags.length,
        }),
        "success",
      );
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={t("outboundPool.title")}
      onClose={onClose}
      footer={
        <div className="sk-row" style={{ gap: 8, justifyContent: "flex-end", width: "100%" }}>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={apply} disabled={busy || presets.loading}>
            {busy ? t("common.loading") : t("outboundPool.apply")}
          </Button>
        </div>
      }
    >
      <div className="sk-stack" style={{ gap: 16 }}>
        <Callout tone="info">{t("outboundPool.about")}</Callout>

        {presets.error && (
          <Callout tone="danger">{presets.error}</Callout>
        )}

        <Field label={t("outboundPool.preset")}>
          <Select
            value={presetId}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => selectPreset(e.target.value)}
          >
            {presetIds.map((id) => (
              <option key={id} value={id}>
                {presets.data?.presets?.[id]?.label || id}
              </option>
            ))}
          </Select>
        </Field>

        {meta?.description && (
          <TextMuted>{meta.description}</TextMuted>
        )}

        <Field label={t("outboundPool.balancerTag")}>
          <Input
            value={balancerTag}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setBalancerTag(e.target.value)}
            className="sk-mono"
            dir="ltr"
          />
        </Field>

        <Field label={t("outboundPool.strategy")}>
          <Select
            value={strategy}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => {
              const v = e.target.value;
              setStrategy(v);
              if (v === "leastPing") setEnableObservatory(true);
            }}
          >
            {strategies.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Field>

        <Field label={t("outboundPool.upstreams")} hint={t("outboundPool.upstreamsHint")}>
          <div className="sk-stack" style={{ gap: 8 }}>
            {rows.map((row, idx) => (
              <div key={idx} className="sk-row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                <Input
                  value={row.address}
                  onChange={(e) => updateRow(idx, { address: e.target.value })}
                  placeholder={t("outboundPool.address")}
                  className="sk-mono"
                  dir="ltr"
                  style={{ minWidth: 140, flex: 1 }}
                />
                <Input
                  value={row.port}
                  onChange={(e) => updateRow(idx, { port: e.target.value })}
                  placeholder={t("outboundPool.port")}
                  className="sk-mono"
                  dir="ltr"
                  style={{ width: 88 }}
                />
                <Input
                  value={row.user}
                  onChange={(e) => updateRow(idx, { user: e.target.value })}
                  placeholder={t("outboundPool.user")}
                  className="sk-mono"
                  dir="ltr"
                  style={{ width: 100 }}
                />
                <Input
                  value={row.pass}
                  onChange={(e) => updateRow(idx, { pass: e.target.value })}
                  placeholder={t("outboundPool.pass")}
                  type="password"
                  className="sk-mono"
                  dir="ltr"
                  style={{ width: 100 }}
                />
                <Button size="sm" variant="danger" onClick={() => removeRow(idx)} disabled={rows.length <= 1}>
                  ×
                </Button>
              </div>
            ))}
            <Button size="sm" onClick={addRow}>
              + {t("outboundPool.addUpstream")}
            </Button>
          </div>
        </Field>

        <label className="sk-row" style={{ gap: 8, alignItems: "center", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={enableObservatory}
            onChange={(e) => setEnableObservatory(e.target.checked)}
          />
          <span>{t("outboundPool.enableObservatory")}</span>
        </label>

        <label className="sk-row" style={{ gap: 8, alignItems: "center", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={addRoutingRule}
            onChange={(e) => setAddRoutingRule(e.target.checked)}
          />
          <span>{t("outboundPool.addRoutingRule")}</span>
        </label>
      </div>
    </Modal>
  );
};

const TextMuted: FC<{ children: ReactNode }> = ({ children }) => (
  <div style={{ fontSize: 13, color: "var(--sk-muted)" }}>{children}</div>
);
