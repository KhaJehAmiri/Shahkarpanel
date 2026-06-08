import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { AmneziaWGParams, NodeItem } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, Field, Input, Pill, useToast } from "../components/ui";
import { IcPlus, IcUsers } from "../components/icons";

const AWG_FIELDS: (keyof AmneziaWGParams)[] = [
  "awg_jc", "awg_jmin", "awg_jmax", "awg_s1", "awg_s2", "awg_h1", "awg_h2", "awg_h3", "awg_h4",
];

const rnd = (min: number, max: number) => Math.floor(Math.random() * (max - min)) + min;

// Sensible AmneziaWG obfuscation preset. H1–H4 must be distinct large ints.
function amneziaPreset(): Required<AmneziaWGParams> {
  const hs = new Set<number>();
  while (hs.size < 4) hs.add(rnd(0x10000000, 0x7fffffff));
  const [h1, h2, h3, h4] = [...hs];
  return {
    awg_jc: rnd(3, 10),
    awg_jmin: 50,
    awg_jmax: 1000,
    awg_s1: rnd(15, 150),
    awg_s2: rnd(15, 150),
    awg_h1: h1, awg_h2: h2, awg_h3: h3, awg_h4: h4,
  };
}

const AmneziaNodeCard: FC<{ node: NodeItem; onSaved: () => void }> = ({ node, onSaved }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const initial = () => {
    const v: Record<string, string> = {};
    for (const f of AWG_FIELDS) {
      const cur = node.wireguard?.[f];
      v[f] = cur === null || cur === undefined ? "" : String(cur);
    }
    return v;
  };
  const [vals, setVals] = useState<Record<string, string>>(initial);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setVals(initial()); /* eslint-disable-next-line */ }, [node.id]);

  const enabled = AWG_FIELDS.some((f) => (node.wireguard?.[f] ?? null) !== null);

  const set = (f: string, val: string) => setVals((p) => ({ ...p, [f]: val }));
  const fill = (p: Required<AmneziaWGParams>) =>
    setVals(Object.fromEntries(AWG_FIELDS.map((f) => [f, String(p[f])])));
  const clearAll = () => setVals(Object.fromEntries(AWG_FIELDS.map((f) => [f, ""])));

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, number | null> = {};
      for (const f of AWG_FIELDS) {
        const raw = vals[f].trim();
        body[f] = raw === "" ? null : Number(raw);
      }
      await api.put(`/node/${node.id}/amneziawg`, body);
      toast.push(t("common.saved"), "success");
      onSaved();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card style={{ padding: 16, marginBottom: 12 }}>
      <div className="nx-row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div className="nx-card-title" style={{ fontSize: 14 }}>{node.name}</div>
        <Pill tone={enabled ? "ok" : "default"}>
          {enabled ? t("wireguard.awgOn") : t("wireguard.awgOff")}
        </Pill>
      </div>
      <div className="nx-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
        {AWG_FIELDS.map((f) => (
          <Field key={f} label={f.replace("awg_", "").toUpperCase()}>
            <Input
              type="number"
              value={vals[f]}
              placeholder="—"
              onChange={(e: any) => set(f, e.target.value)}
            />
          </Field>
        ))}
      </div>
      <div className="nx-row" style={{ gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button size="sm" onClick={() => fill(amneziaPreset())}>{t("wireguard.awgPreset")}</Button>
        <Button size="sm" variant="ghost" onClick={clearAll}>{t("wireguard.awgClear")}</Button>
        <div style={{ flex: 1 }} />
        <Button size="sm" variant="primary" disabled={busy} onClick={save}>{t("common.save")}</Button>
      </div>
    </Card>
  );
};

export const WireGuard: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const { setOpen, requestIntent } = useCopilot();
  const nav = useNavigate();
  const nodes = useFetch<NodeItem[]>(
    () => (admin?.is_sudo ? api.get("/nodes") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const users = useFetch<{ total: number }>(() => api.get("/users?limit=1"), []);

  const wgNodeList = (nodes.data || []).filter((n) => n.core_kind === "wireguard");
  const wgNodes = wgNodeList.length;
  const hasNode = wgNodes > 0;
  const hasUsers = (users.data?.total ?? 0) > 0;

  if (!admin?.is_sudo) {
    return (
      <div>
        <PageHeader title={t("wireguard.title")} subtitle={t("wireguard.subtitle")} />
        <Callout tone="warn">{t("common.sudoOnly")}</Callout>
      </div>
    );
  }

  const steps = [
    { n: 1, title: t("wireguard.step1"), done: hasNode, action: () => { requestIntent("add-wg-node"); nav("/nodes"); } },
    { n: 2, title: t("wireguard.step2"), done: hasUsers, action: () => { requestIntent("create-wg-user"); nav("/users"); } },
    { n: 3, title: t("wireguard.step3"), done: false, action: () => nav("/users") },
  ];

  return (
    <div>
      <PageHeader
        title={t("wireguard.title")}
        subtitle={t("wireguard.subtitle")}
        description={t("wireguard.description")}
        actions={
          <Button variant="ghost" onClick={() => setOpen(true)}>✦ {t("copilot.title")}</Button>
        }
      />

      <Callout tone="info" title={t("wireguard.notXrayTitle")}>
        {t("wireguard.notXrayBody")}
      </Callout>

      <div className="nx-row" style={{ gap: 12, margin: "16px 0" }}>
        <Card style={{ flex: 1, padding: 16 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("wireguard.nodesCount")}</div>
          <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{wgNodes}</div>
        </Card>
        <Card style={{ flex: 1, padding: 16 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("overview.totalUsers")}</div>
          <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{users.data?.total ?? "—"}</div>
        </Card>
      </div>

      <Card>
        <div className="nx-card-title" style={{ marginBottom: 14 }}>{t("wireguard.setupTitle")}</div>
        <div className="nx-stack" style={{ gap: 10 }}>
          {steps.map((s) => (
            <div key={s.n} className="nx-step-row">
              <div className={`nx-step-num ${s.done ? "done" : ""}`}>{s.done ? "✓" : s.n}</div>
              <div style={{ flex: 1 }}>{s.title}</div>
              {s.done ? <Pill tone="ok">{t("common.done")}</Pill> : (
                <Button size="sm" variant="primary" onClick={s.action}>{t("common.start")}</Button>
              )}
            </div>
          ))}
        </div>
      </Card>

      {wgNodes > 0 && (
        <div style={{ marginTop: 20 }}>
          <div className="nx-card-title" style={{ marginBottom: 4 }}>{t("wireguard.awgTitle")}</div>
          <p className="nx-faint" style={{ fontSize: 12, margin: "0 0 12px" }}>{t("wireguard.awgDescription")}</p>
          {wgNodeList.map((n) => (
            <AmneziaNodeCard key={n.id} node={n} onSaved={() => nodes.reload()} />
          ))}
        </div>
      )}

      <div className="nx-row" style={{ marginTop: 16, gap: 10 }}>
        <Button variant="primary" onClick={() => { requestIntent("add-wg-node"); nav("/nodes"); }}>
          <IcPlus className="nx-ico" /> {t("wireguard.addNode")}
        </Button>
        <Button onClick={() => { requestIntent("create-wg-user"); nav("/users"); }}>
          <IcUsers className="nx-ico" /> {t("wireguard.addUser")}
        </Button>
      </div>
    </div>
  );
};
