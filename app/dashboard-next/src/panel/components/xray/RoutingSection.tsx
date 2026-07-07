import { FC, ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { useFetch } from "../../lib/useFetch";
import {
  DOMAIN_STRATEGIES,
  RULE_NETWORKS,
  RULE_PROTOCOLS,
  applyWarpSafeRouting,
  usesWarpRouting,
  listRoutingInboundTags,
  type RoutingRuleForm,
  buildRuleFromForm,
  defaultRule,
  ruleToForm,
} from "../../lib/xrayHelpers";
import { GeoAssetsSection } from "./GeoAssetsSection";
import { ObservatorySection } from "./ObservatorySection";
import {
  addRoutingRule,
  deleteRoutingRule,
  patchRoutingMeta,
  replaceRoutingRules,
  updateRoutingRule,
} from "../../lib/routingRulesCrud";
import { Button, Callout, Card, EmptyState, Field, HelpTip, Input, Modal, MultiSelect, Pill, Select, useToast } from "../ui";
import { IcEdit, IcPlus, IcTrash } from "../icons";

export const RoutingSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave?: () => void;
  saving?: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [tab, setTab] = useState<"rules" | "balancers" | "observatory" | "geo">("rules");
  const [probing, setProbing] = useState(false);
  const [persisting, setPersisting] = useState(false);
  const presets = useFetch<{ presets: Record<string, { label: string; rules?: Record<string, unknown>[] }> }>(
    () => api.get("/routing/presets"),
    [],
  );
  const routing = (config.routing || { rules: [] }) as Record<string, unknown>;
  const rules = (routing.rules || []) as Record<string, unknown>[];
  const [show, setShow] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);

  const setStrategy = async (v: string) => {
    setPersisting(true);
    try {
      onChange(await patchRoutingMeta({ domainStrategy: v }));
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
    } finally {
      setPersisting(false);
    }
  };

  const commitRules = async (saved: Record<string, unknown>) => {
    setPersisting(true);
    try {
      onChange(saved);
      toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
      throw e;
    } finally {
      setPersisting(false);
    }
  };

  const remove = async (idx: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    try {
      await commitRules(await deleteRoutingRule(idx));
    } catch { /* toast shown */ }
  };

  const move = async (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= rules.length) return;
    const next = [...rules];
    [next[idx], next[j]] = [next[j], next[idx]];
    try {
      await commitRules(await replaceRoutingRules(next));
    } catch { /* toast shown */ }
  };

  const ruleMatch = (r: Record<string, unknown>): string => {
    const parts: string[] = [];
    const arr = (v: unknown) => (Array.isArray(v) ? (v as string[]) : v ? [String(v)] : []);
    const dom = arr(r.domain);
    const ip = arr(r.ip);
    const src = arr(r.sourceIP ?? r.source);
    const proto = arr(r.protocol);
    const inb = arr(r.inboundTag);
    if (dom.length) parts.push(`domain: ${dom.slice(0, 2).join(", ")}${dom.length > 2 ? "…" : ""}`);
    if (ip.length) parts.push(`ip: ${ip.slice(0, 2).join(", ")}${ip.length > 2 ? "…" : ""}`);
    if (src.length) parts.push(`src: ${src.slice(0, 1).join(", ")}`);
    if (r.port) parts.push(`port: ${r.port}`);
    if (r.network) parts.push(`net: ${r.network}`);
    if (proto.length) parts.push(`proto: ${proto.join(",")}`);
    if (inb.length) parts.push(`in: ${inb.slice(0, 2).join(", ")}`);
    return parts.join(" · ") || "—";
  };

  const warpRouting = usesWarpRouting(config);
  const inboundTagOptions = listRoutingInboundTags(config);

  const importPreset = async (presetId: string) => {
    const pack = presets.data?.presets?.[presetId];
    if (!pack?.rules?.length) return;
    try {
      await commitRules(await replaceRoutingRules([...(pack.rules as Record<string, unknown>[]), ...rules]));
    } catch { /* toast shown */ }
  };

  const busy = persisting || !!saving;

  const probeLatency = async () => {
    setProbing(true);
    try {
      const res = await api.post<{ probed: number; nodes: { id: number; name: string; latency_ms?: number | null }[] }>(
        "/routing/probe-latency",
      );
      const summary = (res.nodes || [])
        .slice(0, 5)
        .map((n) => `${n.name}: ${n.latency_ms ?? "—"}ms`)
        .join(" · ");
      toast.push(
        t("xray.probeLatencyDone", { defaultValue: "Probed {{n}} node(s). {{summary}}", n: res.probed, summary }),
        "success",
      );
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setProbing(false);
    }
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.routingTitle")}>{t("xray.routingDesc")}</Callout>
      <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
        <Button size="sm" variant={tab === "rules" ? "primary" : "ghost"} onClick={() => setTab("rules")}>
          {t("xray.rulesTab", { defaultValue: "Rules" })}
        </Button>
        <Button size="sm" variant={tab === "balancers" ? "primary" : "ghost"} onClick={() => setTab("balancers")}>
          {t("xray.balancersTab", { defaultValue: "Balancers" })}
        </Button>
        <Button size="sm" variant={tab === "observatory" ? "primary" : "ghost"} onClick={() => setTab("observatory")}>
          {t("xray.observatoryTab")}
        </Button>
        <Button size="sm" variant={tab === "geo" ? "primary" : "ghost"} onClick={() => setTab("geo")}>
          {t("xray.geoAssetsTab", { defaultValue: "Geo assets" })}
        </Button>
        <Button size="sm" disabled={probing} onClick={() => void probeLatency()}>
          {probing ? t("common.loading") : t("xray.probeLatency", { defaultValue: "Probe node latency" })}
        </Button>
      </div>
      {tab === "geo" ? (
        <GeoAssetsSection />
      ) : tab === "observatory" ? (
        <ObservatorySection config={config} onChange={onChange} />
      ) : tab === "balancers" ? (
        <BalancersSection config={config} onChange={onChange} onSave={onSave} saving={!!saving} />
      ) : (
      <>
      {warpRouting && (
        <Callout tone="warn" title={t("xray.warpRoutingWarnTitle")}>
          {t("xray.warpRoutingWarnBody")}
          <div className="nx-row" style={{ marginTop: 10 }}>
            <Button size="sm" onClick={() => onChange(applyWarpSafeRouting(config))}>
              {t("xray.warpRoutingFix")}
            </Button>
          </div>
        </Callout>
      )}
      <Card>
        <Field label={t("xray.domainStrategy")}>
          <Select
            value={String(routing.domainStrategy || "AsIs")}
            disabled={busy}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => void setStrategy(e.target.value)}
          >
            {DOMAIN_STRATEGIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
      </Card>
      {presets.data && Object.keys(presets.data.presets || {}).length > 0 && (
        <Card>
          <div className="nx-faint" style={{ fontSize: 12, marginBottom: 8 }}>
            {t("xray.routingPresetsHint", { defaultValue: "Import built-in rule packs (prepended to current rules)" })}
          </div>
          <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
            {Object.entries(presets.data.presets).map(([id, meta]) => (
              <Button key={id} size="sm" disabled={busy} onClick={() => void importPreset(id)}>
                {meta.label || id}
              </Button>
            ))}
          </div>
        </Card>
      )}
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" onClick={() => { setEditIdx(null); setShow(true); }}>
          <IcPlus className="nx-ico" /> {t("xray.addRule")}
        </Button>
      </div>
      <Card pad0>
        {!rules.length ? (
          <EmptyState title={t("common.noData")} desc={t("xray.noRulesHint")} />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("xray.ruleTag")}</th>
                  <th>{t("xray.matchCols")}</th>
                  <th>{t("xray.target")}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r, idx) => (
                  <tr key={idx}>
                    <td className="nx-faint">{idx + 1}</td>
                    <td>{String(r.ruleTag || "—")}</td>
                    <td className="nx-mono" style={{ fontSize: 11 }}>{ruleMatch(r)}</td>
                    <td>
                      <Pill tone={r.balancerTag ? "warn" : "accent"}>
                        {String(r.balancerTag || r.outboundTag || "—")}
                      </Pill>
                    </td>
                    <td>
                      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 4 }}>
                        <Button size="sm" onClick={() => void move(idx, -1)} disabled={busy || idx === 0}>↑</Button>
                        <Button size="sm" onClick={() => void move(idx, 1)} disabled={busy || idx === rules.length - 1}>↓</Button>
                        <Button size="sm" disabled={busy} onClick={() => { setEditIdx(idx); setShow(true); }}><IcEdit className="nx-ico" /></Button>
                        <Button variant="danger" size="sm" disabled={busy} onClick={() => void remove(idx)}><IcTrash className="nx-ico" /></Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {show && (
        <RuleModal
          rule={editIdx != null ? rules[editIdx] : null}
          config={config}
          inboundTagOptions={inboundTagOptions}
          busy={busy}
          onClose={() => setShow(false)}
          onApply={async (rule) => {
            try {
              if (editIdx != null) {
                await commitRules(await updateRoutingRule(editIdx, rule));
              } else {
                await commitRules(await addRoutingRule(rule));
              }
              setShow(false);
            } catch { /* toast shown */ }
          }}
        />
      )}
      </>
      )}
    </div>
  );
};

const BalancersSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave?: () => void;
  saving?: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const routing = (config.routing || { balancers: [] }) as Record<string, unknown>;
  const balancers = (routing.balancers || []) as Record<string, unknown>[];
  const outbounds = (config.outbounds || []) as Record<string, unknown>[];
  const outboundTags = outbounds.map((o) => String(o.tag || "")).filter(Boolean);

  const applyBalancers = (next: Record<string, unknown>[]) => {
    onChange({ ...config, routing: { ...routing, balancers: next } });
  };

  const update = (idx: number, field: string, value: unknown) => {
    const next = [...balancers];
    next[idx] = { ...next[idx], [field]: value };
    applyBalancers(next);
  };

  const add = () => {
    applyBalancers([...balancers, { tag: `balancer-${balancers.length + 1}`, selector: outboundTags.slice(0, 1) }]);
  };

  const remove = (idx: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    const next = [...balancers];
    next.splice(idx, 1);
    applyBalancers(next);
  };

  return (
    <>
      <Callout tone="info">{t("xray.balancersHint", { defaultValue: "Balancers load-balance traffic across multiple outbounds. Reference a balancer tag from a routing rule." })}</Callout>
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" size="sm" onClick={add}><IcPlus className="nx-ico" /> {t("xray.addBalancer", { defaultValue: "Add balancer" })}</Button>
      </div>
      <Card pad0>
        {!balancers.length ? (
          <EmptyState title={t("common.noData")} desc={t("xray.noBalancersHint", { defaultValue: "No balancers yet." })} />
        ) : (
          <div className="nx-table-wrap">
            <table className="nx-table">
              <thead>
                <tr>
                  <th>{t("xray.ruleTag")}</th>
                  <th>{t("xray.balancerSelectors", { defaultValue: "Selectors" })}</th>
                  <th>{t("xray.balancerStrategy", { defaultValue: "Strategy" })}</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {balancers.map((b, idx) => (
                  <tr key={idx}>
                    <td><Input value={String(b.tag || "")} onChange={(e) => update(idx, "tag", e.target.value)} /></td>
                    <td>
                      <MultiSelect
                        values={(b.selector as string[]) || []}
                        options={outboundTags}
                        allowCustom
                        onChange={(next) => update(idx, "selector", next)}
                      />
                    </td>
                    <td>
                      <Select
                        value={String((b.strategy as Record<string, unknown>)?.type || "random")}
                        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => update(idx, "strategy", { type: e.target.value })}
                      >
                        {["random", "roundRobin", "leastPing", "leastLoad"].map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </Select>
                    </td>
                    <td>
                      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
                        <Button variant="danger" size="sm" onClick={() => remove(idx)}><IcTrash className="nx-ico" /></Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={saving} onClick={() => onSave?.()}>{t("common.save")}</Button>
      </div>
    </>
  );
};

const FormRow: FC<{ label: string; help?: string; sep?: boolean; children: ReactNode }> = ({ label, help, sep, children }) => (
  <div className="nx-form-h-row">
    {sep && <div className="nx-form-h-sep" aria-hidden />}
    <div className="nx-form-h-label">
      <span>{label}</span>
      {help && <HelpTip text={help} placement="bottom" />}
    </div>
    <div className="nx-form-h-ctrl">{children}</div>
  </div>
);

const RuleModal: FC<{
  rule: Record<string, unknown> | null;
  config: Record<string, unknown>;
  inboundTagOptions: string[];
  busy?: boolean;
  onClose: () => void;
  onApply: (r: Record<string, unknown>) => void | Promise<void>;
}> = ({ rule, config, inboundTagOptions, busy, onClose, onApply }) => {
  const { t } = useTranslation();
  const [f, setF] = useState<RoutingRuleForm>(rule ? ruleToForm(rule) : defaultRule());

  const upd = (k: keyof RoutingRuleForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  const outbounds = (config.outbounds || []) as Record<string, unknown>[];
  const routing = (config.routing || {}) as Record<string, unknown>;
  const balancers = (routing.balancers || []) as Record<string, unknown>[];

  const outboundTags = ["", ...outbounds.map((o) => String(o.tag)).filter(Boolean)];
  const inboundTags = inboundTagOptions;
  const balancerTags = ["", ...balancers.map((b) => String(b.tag)).filter(Boolean)];

  const addAttr = () => setF((p) => ({ ...p, attrs: [...p.attrs, { key: "", value: "" }] }));
  const updAttr = (idx: number, key: "key" | "value", val: string) =>
    setF((p) => ({ ...p, attrs: p.attrs.map((a, i) => (i === idx ? { ...a, [key]: val } : a)) }));
  const removeAttr = (idx: number) =>
    setF((p) => ({ ...p, attrs: p.attrs.filter((_, i) => i !== idx) }));

  return (
    <Modal
      open
      formWide
      title={rule ? t("common.edit") : t("xray.addRule")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>
          <Button variant="primary" disabled={busy} onClick={() => void onApply(buildRuleFromForm(f))}>
            {rule ? t("common.save") : t("common.create")}
          </Button>
        </>
      }
    >
      <div className="nx-form-h">
        <FormRow label={t("xray.sourceIp")} help={t("xray.useComma")}>
          <Input value={f.sourceIP} onChange={upd("sourceIP")} placeholder="0.0.0.0/8, fc00::/7, geoip:ir" />
        </FormRow>
        <FormRow label={t("xray.sourcePort")} help={t("xray.useComma")}>
          <Input value={f.sourcePort} onChange={upd("sourcePort")} placeholder="53,443,1000-2000" />
        </FormRow>
        <FormRow label={t("xray.vlessRoute")} help={t("xray.vlessRouteHint")}>
          <Input value={f.vlessRoute} onChange={upd("vlessRoute")} placeholder="53,443,1000-2000" />
        </FormRow>
        <FormRow label="Network">
          <Select value={f.network} onChange={upd("network")}>
            {RULE_NETWORKS.map((n) => <option key={n || "any"} value={n}>{n || `(${t("common.all")})`}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Protocol" help={t("xray.protocolHint")}>
          <MultiSelect
            values={f.protocol}
            options={[...RULE_PROTOCOLS]}
            onChange={(next) => setF((p) => ({ ...p, protocol: next }))}
          />
        </FormRow>
        <FormRow label={t("xray.attrs")} help={t("xray.attrsHint")}>
          <div className="nx-form-h-attrs">
            <Button size="sm" onClick={addAttr}><IcPlus className="nx-ico" /></Button>
            {f.attrs.map((a, idx) => (
              <div className="nx-attr-row" key={idx}>
                <Input value={a.key} onChange={(e: React.ChangeEvent<HTMLInputElement>) => updAttr(idx, "key", e.target.value)} placeholder=":method" />
                <Input value={a.value} onChange={(e: React.ChangeEvent<HTMLInputElement>) => updAttr(idx, "value", e.target.value)} placeholder="GET" />
                <Button variant="danger" size="sm" onClick={() => removeAttr(idx)}><IcTrash className="nx-ico" /></Button>
              </div>
            ))}
          </div>
        </FormRow>

        <FormRow label="IP" help={t("xray.ipHint")} sep>
          <Input value={f.ip} onChange={upd("ip")} placeholder="0.0.0.0/8, fc00::/7, geoip:ir" />
        </FormRow>
        <FormRow label={t("xray.domainName")} help={t("xray.useComma")}>
          <Input value={f.domain} onChange={upd("domain")} placeholder="google.com, geosite:cn" />
        </FormRow>
        <FormRow label="User" help={t("xray.useComma")}>
          <Input value={f.user} onChange={upd("user")} placeholder="email address" />
        </FormRow>
        <FormRow label="Port" help={t("xray.useComma")}>
          <Input value={f.port} onChange={upd("port")} placeholder="53,443,1000-2000" />
        </FormRow>
        <FormRow label={t("xray.inboundTags")} help={t("xray.inboundTagsHint")}>
          <MultiSelect
            values={f.inboundTag}
            options={inboundTags}
            customPlaceholder={t("xray.inboundTagCustom")}
            allowCustom
            onChange={(next) => setF((p) => ({ ...p, inboundTag: next }))}
          />
        </FormRow>
        <FormRow label={t("xray.outboundTag")} help={f.balancerTag.trim() ? t("xray.outboundTagDisabled") : undefined}>
          <Select value={f.outboundTag} onChange={upd("outboundTag")} disabled={!!f.balancerTag.trim()}>
            {outboundTags.map((tag) => <option key={tag || "none"} value={tag}>{tag || "(none)"}</option>)}
          </Select>
        </FormRow>
        <FormRow label={t("xray.balancerTag")} help={t("xray.balancerTagHint")}>
          {balancerTags.length > 1 ? (
            <Select value={f.balancerTag} onChange={upd("balancerTag")}>
              {balancerTags.map((tag) => <option key={tag || "none"} value={tag}>{tag || "(none)"}</option>)}
            </Select>
          ) : (
            <Input value={f.balancerTag} onChange={upd("balancerTag")} placeholder="(none)" />
          )}
        </FormRow>
      </div>
    </Modal>
  );
};
