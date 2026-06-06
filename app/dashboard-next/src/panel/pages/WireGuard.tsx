import { FC } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { useCopilot } from "../copilot/CopilotContext";
import { useFetch } from "../lib/useFetch";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, Pill } from "../components/ui";
import { IcPlus, IcUsers } from "../components/icons";

export const WireGuard: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const { setOpen, requestIntent } = useCopilot();
  const nav = useNavigate();
  const nodes = useFetch<{ core_kind?: string }[]>(
    () => (admin?.is_sudo ? api.get("/nodes") : Promise.resolve([])),
    [admin?.is_sudo],
  );
  const users = useFetch<{ total: number }>(() => api.get("/users?limit=1"), []);

  const wgNodes = (nodes.data || []).filter((n) => n.core_kind === "wireguard").length;
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
