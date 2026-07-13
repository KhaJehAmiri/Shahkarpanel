import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { AmneziaWGParams, NodeItem } from "../api/types";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch } from "../lib/useFetch";
import { copyToClipboard } from "../lib/clipboard";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, Field, Input, Pill, useToast, SkeletonRows } from "../components/ui";
import { IcPlus, IcUsers } from "../components/icons";

const AWG_FIELDS: (keyof AmneziaWGParams)[] = [
  "awg_jc", "awg_jmin", "awg_jmax", "awg_s1", "awg_s2", "awg_s3", "awg_s4",
  "awg_h1", "awg_h2", "awg_h3", "awg_h4",
];

const rnd = (min: number, max: number) => Math.floor(Math.random() * (max - min)) + min;

// Sensible AmneziaWG obfuscation preset. H1–H4 must be distinct large ints.
function amneziaPreset(): Pick<AmneziaWGParams, "awg_jc" | "awg_jmin" | "awg_jmax" | "awg_s1" | "awg_s2" | "awg_h1" | "awg_h2" | "awg_h3" | "awg_h4"> {
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

type WgStatus = {
  plain_enabled: boolean;
  awg_enabled: boolean;
  sg_wire_enabled?: boolean;
  sg_wire_preset_rev?: string | null;
  runtime_ready: boolean;
  node_connected: boolean;
  needs_agent_upgrade: boolean;
};

const AmneziaNodeCard: FC<{
  node: NodeItem;
  onSaved: () => void;
  sgWireFlag?: boolean;
}> = ({ node, onSaved, sgWireFlag }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [plainOn, setPlainOn] = useState(node.wireguard?.plain_enabled !== false);
  const [awgOn, setAwgOn] = useState(!!node.wireguard?.awg_enabled);
  const [sgWireOn, setSgWireOn] = useState(!!node.wireguard?.sg_wire_enabled);
  const [xrayOn, setXrayOn] = useState(!!node.wireguard?.xray_wg_enabled);
  const [xrayPort, setXrayPort] = useState(
    node.wireguard?.xray_wg_listen_port != null ? String(node.wireguard.xray_wg_listen_port) : "51901",
  );
  const [directPort, setDirectPort] = useState(
    node.wireguard?.direct_listen_port != null ? String(node.wireguard.direct_listen_port) : "",
  );
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
  const [status, setStatus] = useState<WgStatus | null>(null);
  useEffect(() => {
    setVals(initial());
    setPlainOn(node.wireguard?.plain_enabled !== false);
    setAwgOn(!!node.wireguard?.awg_enabled);
    setSgWireOn(!!node.wireguard?.sg_wire_enabled);
    setXrayOn(!!node.wireguard?.xray_wg_enabled);
    setXrayPort(
      node.wireguard?.xray_wg_listen_port != null ? String(node.wireguard.xray_wg_listen_port) : "51901",
    );
    setDirectPort(
      node.wireguard?.direct_listen_port != null ? String(node.wireguard.direct_listen_port) : "",
    );
    /* eslint-disable-next-line */
  }, [node.id]);

  const loadStatus = async () => {
    try {
      setStatus(await api.get<WgStatus>(`/node/${node.id}/amneziawg/status`));
    } catch {
      setStatus(null);
    }
  };
  useEffect(() => { loadStatus(); /* eslint-disable-next-line */ }, [node.id, node.wireguard]);

  const set = (f: string, val: string) => setVals((p) => ({ ...p, [f]: val }));
  const fill = (p: Partial<AmneziaWGParams>) =>
    setVals((prev) => {
      const next = { ...prev };
      for (const f of AWG_FIELDS) {
        const v = p[f];
        if (v !== undefined && v !== null) next[f] = String(v);
      }
      return next;
    });
  const clearAll = () => setVals(Object.fromEntries(AWG_FIELDS.map((f) => [f, ""])));

  const saveBody = () => {
    const body: Record<string, number | null> = {};
    for (const f of AWG_FIELDS) {
      const raw = vals[f].trim();
      body[f] = raw === "" ? null : Number(raw);
    }
    return body;
  };

  const saveStack = async () => {
    if (!plainOn && !awgOn && !xrayOn) {
      toast.push(t("wireguard.stackRequired"), "error");
      return;
    }
    setBusy(true);
    try {
      const directRaw = directPort.trim();
      const direct_listen_port =
        directRaw === "" ? undefined : Number(directRaw);
      if (directRaw !== "" && (!Number.isFinite(direct_listen_port!) || direct_listen_port! < 0 || direct_listen_port! > 65535)) {
        toast.push(t("wireguard.badPort"), "error");
        setBusy(false);
        return;
      }
      await api.put(`/node/${node.id}/wireguard/stack`, {
        plain_enabled: plainOn,
        awg_enabled: awgOn,
        ...(direct_listen_port !== undefined ? { direct_listen_port } : {}),
      });
      if (awgOn) {
        const body = saveBody();
        const hasParams = AWG_FIELDS.some((f) => body[f] !== null);
        if (!hasParams && !sgWireOn) {
          const preset = amneziaPreset();
          await api.put(`/node/${node.id}/amneziawg`, preset);
        } else if (hasParams) {
          await api.put(`/node/${node.id}/amneziawg`, body);
        }
      }
      if (sgWireFlag) {
        await api.put(`/node/${node.id}/sigmaguard-wire`, { enabled: sgWireOn });
      }
      const xrayBody: { enabled: boolean; listen_port?: number } = { enabled: xrayOn };
      if (xrayOn) {
        const xp = Number(xrayPort.trim() || "51901");
        if (!Number.isFinite(xp) || xp < 1 || xp > 65535) {
          toast.push(t("wireguard.badPort"), "error");
          setBusy(false);
          return;
        }
        xrayBody.listen_port = xp;
      }
      await api.put(`/node/${node.id}/wireguard/xray-native`, xrayBody);
      toast.push(t("common.saved"), "success");
      onSaved();
      await loadStatus();
      const st = await api.get<WgStatus>(`/node/${node.id}/amneziawg/status`);
      if (st.awg_enabled && !st.node_connected) {
        toast.push(t("wireguard.awgNodeOffline"), "info");
      } else if (st.needs_agent_upgrade) {
        toast.push(t("wireguard.awgNeedsUpgrade"), "info");
      } else if (st.awg_enabled && st.runtime_ready) {
        toast.push(t("wireguard.awgRuntimeReady"), "success");
      }
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const saveParams = async () => {
    setBusy(true);
    try {
      await api.put(`/node/${node.id}/amneziawg`, saveBody());
      toast.push(t("common.saved"), "success");
      onSaved();
      await loadStatus();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const copyUpgrade = async () => {
    try {
      const res = await api.get<{ install_command: string }>(
        `/nodes/install-command?name=${encodeURIComponent(node.name)}&core_kind=wireguard&rebuild=1`,
      );
      const ok = await copyToClipboard(res.install_command);
      toast.push(ok ? t("common.copiedToClipboard") : t("common.copyFailed"), ok ? "success" : "error");
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const statusPill = () => {
    const parts: string[] = [];
    if (plainOn) parts.push(t("wg.portPillPlain", { port: node.wireguard?.listen_port ?? 51820 }));
    if (awgOn) parts.push(t("wg.portPillAwg", { port: status?.runtime_ready ? 51821 : "51821?" }));
    if (xrayOn) parts.push(t("wireguard.xrayPill", { port: xrayPort || "51901" }));
    if (directPort.trim()) parts.push(t("wireguard.directPill", { port: directPort.trim() }));
    if (!parts.length) return <Pill tone="default">{t("wireguard.awgOff")}</Pill>;
    return <Pill tone={status?.needs_agent_upgrade ? "warn" : "ok"}>{parts.join(" + ")}</Pill>;
  };

  return (
    <Card style={{ padding: 16, marginBottom: 12 }}>
      <div className="nx-row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div className="nx-card-title" style={{ fontSize: 14 }}>{node.name}</div>
        {statusPill()}
      </div>
      <div className="nx-row" style={{ gap: 16, marginBottom: 12, flexWrap: "wrap" }}>
        <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={plainOn} onChange={(e) => setPlainOn(e.target.checked)} />
          {t("infra.enablePlainWg")}
        </label>
        <label className="nx-row" style={{ gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={awgOn} onChange={(e) => setAwgOn(e.target.checked)} />
          {t("infra.enableAwgWg")}
        </label>
        <label className="nx-row" style={{ gap: 8, fontSize: 13 }} title={t("wireguard.xrayHint")}>
          <input type="checkbox" checked={xrayOn} onChange={(e) => setXrayOn(e.target.checked)} />
          {t("wireguard.xrayEnable")}
        </label>
        {sgWireFlag && (
          <label className="nx-row" style={{ gap: 8, fontSize: 13 }} title={t("wireguard.sgWireHint")}>
            <input
              type="checkbox"
              checked={sgWireOn}
              onChange={(e) => {
                setSgWireOn(e.target.checked);
                if (e.target.checked) setAwgOn(true);
              }}
            />
            {t("wireguard.sgWireEnable")}
          </label>
        )}
      </div>
      <div className="nx-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 12 }}>
        {xrayOn && (
          <Field label={t("wireguard.xrayPort")}>
            <Input type="number" value={xrayPort} placeholder="51901" onChange={(e: any) => setXrayPort(e.target.value)} />
          </Field>
        )}
        <Field label={t("wireguard.directPort")} hint={t("wireguard.directPortHint")}>
          <Input
            type="number"
            value={directPort}
            placeholder={t("wireguard.directPortPlaceholder")}
            onChange={(e: any) => setDirectPort(e.target.value)}
          />
        </Field>
      </div>
      {xrayOn && (
        <div style={{ marginBottom: 10 }}>
          <Callout tone="info">{t("wireguard.xrayBody")}</Callout>
        </div>
      )}
      {sgWireOn && status?.sg_wire_preset_rev && (
        <div style={{ marginBottom: 10 }}>
          <Callout tone="info">
            {t("wireguard.sgWirePreset", { rev: status.sg_wire_preset_rev })}
          </Callout>
        </div>
      )}
      {awgOn && <div className="nx-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
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
      </div>}
      <div className="nx-row" style={{ gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        {awgOn && (
          <>
            <Button size="sm" onClick={() => fill(amneziaPreset())}>{t("wireguard.awgPreset")}</Button>
            <Button size="sm" variant="ghost" onClick={clearAll}>{t("wireguard.awgClear")}</Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={saveParams}>{t("wireguard.awgSaveParams")}</Button>
          </>
        )}
        {status?.needs_agent_upgrade && (
          <Button size="sm" variant="ghost" onClick={copyUpgrade}>{t("wireguard.awgCopyUpgrade")}</Button>
        )}
        <div style={{ flex: 1 }} />
        <Button size="sm" variant="primary" disabled={busy} onClick={saveStack}>{t("wireguard.stackSave")}</Button>
      </div>
    </Card>
  );
};

export const WireGuard: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const { setOpen, requestIntent } = useCopilot();
  const nav = useNavigate();
  const nodes = useFetch<NodeItem[]>(
    () => (admin?.is_sudo ? api.get("/nodes") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const flags = useFetch<{ name: string; enabled: boolean }[]>(
    () => (admin?.is_sudo ? api.get("/feature-flags") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const sgWireFlag = !!(flags.data || []).find((f) => f.name === "sigmaguard_wire")?.enabled;
  const users = useFetch<{ total: number }>(() => api.get("/users?limit=1"), []);

  const wgNodeList = (nodes.data || []).filter(
    (n) => n.core_kind === "wireguard" || !!n.wireguard,
  );
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
    { n: 1, title: t("wireguard.step1"), done: hasNode, action: () => { requestIntent("add-wg-node"); nav("/servers?tab=nodes"); } },
    { n: 2, title: t("wireguard.step2"), done: hasUsers, action: () => { requestIntent("create-wg-user"); nav("/users"); } },
    { n: 3, title: t("wireguard.step3"), done: hasNode && hasUsers, action: () => nav("/users") },
  ];

  return (
    <div>
      {!embedded && (
        <PageHeader
          title={t("wireguard.title")}
          subtitle={t("wireguard.subtitle")}
          description={t("wireguard.description")}
          actions={
            <Button variant="ghost" onClick={() => setOpen(true)}>✦ {t("copilot.title")}</Button>
          }
        />
      )}

      {!embedded && <Callout tone="info" title={t("wireguard.notXrayTitle")}>
        {t("wireguard.notXrayBody")}
      </Callout>}

      <div className="nx-row" style={{ gap: 12, margin: "16px 0" }}>
        <Card style={{ flex: 1, padding: 16 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("wireguard.nodesCount")}</div>
          {nodes.loading ? <SkeletonRows rows={1} cols={1} /> : <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{wgNodes}</div>}
        </Card>
        <Card style={{ flex: 1, padding: 16 }}>
          <div className="nx-faint" style={{ fontSize: 12 }}>{t("overview.totalUsers")}</div>
          {users.loading ? <SkeletonRows rows={1} cols={1} /> : <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{users.data?.total ?? "—"}</div>}
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
            <AmneziaNodeCard key={n.id} node={n} onSaved={() => nodes.reload()} sgWireFlag={sgWireFlag} />
          ))}
        </div>
      )}

      <div className="nx-row" style={{ marginTop: 16, gap: 10 }}>
        <Button variant="primary" onClick={() => { requestIntent("add-wg-node"); nav("/servers?tab=nodes"); }}>
          <IcPlus className="nx-ico" /> {t("wireguard.addNode")}
        </Button>
        <Button onClick={() => { requestIntent("create-wg-user"); nav("/users"); }}>
          <IcUsers className="nx-ico" /> {t("wireguard.addUser")}
        </Button>
      </div>
    </div>
  );
};
