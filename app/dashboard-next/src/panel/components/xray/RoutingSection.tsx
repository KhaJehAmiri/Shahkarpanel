import { FC, ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { Button, Callout, Card, EmptyState, Field, HelpTip, Input, Modal, MultiSelect, Pill, Select } from "../ui";
import { IcEdit, IcPlus, IcTrash } from "../icons";

export const RoutingSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const routing = (config.routing || { rules: [] }) as Record<string, unknown>;
  const rules = (routing.rules || []) as Record<string, unknown>[];
  const [show, setShow] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);

  const setStrategy = (v: string) => {
    onChange({ ...config, routing: { ...routing, domainStrategy: v } });
  };

  const applyRules = (next: Record<string, unknown>[]) => {
    onChange({ ...config, routing: { ...routing, rules: next } });
  };

  const remove = (idx: number) => {
    if (!confirm(t("common.confirmDelete"))) return;
    const next = [...rules];
    next.splice(idx, 1);
    applyRules(next);
  };

  const move = (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= rules.length) return;
    const next = [...rules];
    [next[idx], next[j]] = [next[j], next[idx]];
    applyRules(next);
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

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.routingTitle")}>{t("xray.routingDesc")}</Callout>
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
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setStrategy(e.target.value)}
          >
            {DOMAIN_STRATEGIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
      </Card>
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
                        <Button size="sm" onClick={() => move(idx, -1)} disabled={idx === 0}>↑</Button>
                        <Button size="sm" onClick={() => move(idx, 1)} disabled={idx === rules.length - 1}>↓</Button>
                        <Button size="sm" onClick={() => { setEditIdx(idx); setShow(true); }}><IcEdit className="nx-ico" /></Button>
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
        <Button variant="primary" disabled={saving} onClick={onSave}>{t("common.save")}</Button>
      </div>
      {show && (
        <RuleModal
          rule={editIdx != null ? rules[editIdx] : null}
          config={config}
          inboundTagOptions={inboundTagOptions}
          onClose={() => setShow(false)}
          onApply={(rule) => {
            const next = [...rules];
            if (editIdx != null) next[editIdx] = rule;
            else next.push(rule);
            applyRules(next);
            setShow(false);
          }}
        />
      )}
    </div>
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
  onClose: () => void;
  onApply: (r: Record<string, unknown>) => void;
}> = ({ rule, config, inboundTagOptions, onClose, onApply }) => {
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
          <Button variant="primary" onClick={() => onApply(buildRuleFromForm(f))}>
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
