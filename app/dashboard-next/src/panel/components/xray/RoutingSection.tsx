import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { DOMAIN_STRATEGIES, buildRuleFromForm, defaultRule, ruleToForm } from "../../lib/xrayHelpers";
import { Button, Callout, Card, EmptyState, Field, Input, Modal, Select } from "../ui";
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

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.routingTitle")}>{t("xray.routingDesc")}</Callout>
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
                  <th>{t("xray.outboundTag")}</th>
                  <th>IP / Domain</th>
                  <th style={{ textAlign: "end" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r, idx) => (
                  <tr key={idx}>
                    <td className="nx-faint">{idx + 1}</td>
                    <td><b>{String(r.outboundTag || "—")}</b></td>
                    <td className="nx-mono" style={{ fontSize: 11 }}>
                      {[...(Array.isArray(r.ip) ? r.ip : []), ...(Array.isArray(r.domain) ? r.domain : [])].slice(0, 2).join(" · ") || "—"}
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
          outbounds={(config.outbounds || []) as Record<string, unknown>[]}
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

const RuleModal: FC<{
  rule: Record<string, unknown> | null;
  outbounds: Record<string, unknown>[];
  onClose: () => void;
  onApply: (r: Record<string, unknown>) => void;
}> = ({ rule, outbounds, onClose, onApply }) => {
  const { t } = useTranslation();
  const [f, setF] = useState(rule ? ruleToForm(rule) : defaultRule());
  const upd = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  const tags = outbounds.map((o) => String(o.tag)).filter(Boolean);

  return (
    <Modal
      open
      title={rule ? t("common.edit") : t("xray.addRule")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" onClick={() => onApply(buildRuleFromForm(f))}>{t("common.save")}</Button>
        </>
      }
    >
      <div className="nx-stack">
        <Field label={t("xray.outboundTag")}>
          <Select value={f.outboundTag} onChange={upd("outboundTag")}>
            {tags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
          </Select>
        </Field>
        <Field label={`${t("xray.inboundTag")} (${t("common.optional")})`}>
          <Input value={f.inboundTag} onChange={upd("inboundTag")} placeholder="VLESS WS, comma-separated" />
        </Field>
        <Field label={`IP (${t("xray.ruleListHint")})`}>
          <Input value={f.ip} onChange={upd("ip")} placeholder="geoip:private, 10.0.0.0/8" />
        </Field>
        <Field label={`Domain (${t("xray.ruleListHint")})`}>
          <Input value={f.domain} onChange={upd("domain")} placeholder="geosite:category-ads-all" />
        </Field>
        <div className="nx-row" style={{ gap: 12 }}>
          <Field label={`Port (${t("common.optional")})`}><Input value={f.port} onChange={upd("port")} /></Field>
          <Field label={`Network (${t("common.optional")})`}><Input value={f.network} onChange={upd("network")} placeholder="tcp,udp" /></Field>
        </div>
      </div>
    </Modal>
  );
};
