import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { DedicatedIPPool } from "../api/types";
import { useApp } from "../context/AppContext";
import { useFetch } from "../lib/useFetch";
import { formatDate } from "../lib/format";
import { PageHeader } from "../components/Shell";
import { Button, Callout, Card, Field, Input, Pill, SkeletonRows, useToast } from "../components/ui";

export const DedicatedIP: FC = () => {
  const { t } = useTranslation();
  const { admin } = useApp();
  const toast = useToast();
  const pool = useFetch<DedicatedIPPool>(
    () => (admin?.is_sudo ? api.get("/dedicated-ip") : Promise.resolve(null as any)),
    [admin?.is_sudo],
  );

  const [address, setAddress] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [assignUser, setAssignUser] = useState("");
  const [busy, setBusy] = useState(false);

  if (!admin?.is_sudo) {
    return (
      <div>
        <PageHeader title={t("dedip.title")} subtitle={t("dedip.subtitle")} />
        <Callout tone="warn">{t("common.sudoOnly")}</Callout>
      </div>
    );
  }

  // A 404 here means the client_api feature flag is off.
  const flagOff = pool.status === 404;

  const addIP = async () => {
    if (!address.trim()) return;
    setBusy(true);
    try {
      await api.post("/dedicated-ip", { address: address.trim(), node_id: nodeId ? Number(nodeId) : null });
      toast.push(t("common.created"), "success");
      setAddress(""); setNodeId("");
      pool.reload();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const assign = async () => {
    if (!assignUser.trim()) return;
    setBusy(true);
    try {
      await api.post("/dedicated-ip/assign", { username: assignUser.trim() });
      toast.push(t("dedip.assigned"), "success");
      setAssignUser("");
      pool.reload();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  const release = async (username?: string | null) => {
    if (!username) return;
    setBusy(true);
    try {
      await api.post("/dedicated-ip/release", { username });
      toast.push(t("dedip.released"), "success");
      pool.reload();
    } catch (e: any) { toast.push(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title={t("dedip.title")} subtitle={t("dedip.subtitle")} description={t("dedip.description")} />

      {flagOff && (
        <Callout tone="warn" title={t("dedip.flagOffTitle")}>{t("dedip.flagOffBody")}</Callout>
      )}

      {!flagOff && (
        <>
          <div className="nx-row" style={{ gap: 12, margin: "16px 0" }}>
            <Card style={{ flex: 1, padding: 16 }}>
              <div className="nx-faint" style={{ fontSize: 12 }}>{t("dedip.total")}</div>
              <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{pool.data?.total ?? "—"}</div>
            </Card>
            <Card style={{ flex: 1, padding: 16 }}>
              <div className="nx-faint" style={{ fontSize: 12 }}>{t("dedip.assignedCount")}</div>
              <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{pool.data?.assigned ?? "—"}</div>
            </Card>
            <Card style={{ flex: 1, padding: 16 }}>
              <div className="nx-faint" style={{ fontSize: 12 }}>{t("dedip.free")}</div>
              <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{pool.data?.free ?? "—"}</div>
            </Card>
          </div>

          <Card style={{ padding: 16, marginBottom: 16 }}>
            <div className="nx-card-title" style={{ marginBottom: 12 }}>{t("dedip.addTitle")}</div>
            <div className="nx-row" style={{ gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
              <Field label={t("dedip.address")}>
                <Input value={address} placeholder="203.0.113.10" onChange={(e: any) => setAddress(e.target.value)} />
              </Field>
              <Field label={`${t("dedip.nodeId")} (${t("common.optional")})`}>
                <Input type="number" value={nodeId} placeholder="—" onChange={(e: any) => setNodeId(e.target.value)} />
              </Field>
              <Button variant="primary" disabled={busy} onClick={addIP}>{t("dedip.addBtn")}</Button>
            </div>
            <div className="nx-row" style={{ gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginTop: 14 }}>
              <Field label={t("dedip.assignUser")} hint={t("dedip.assignHint")}>
                <Input value={assignUser} placeholder="username" onChange={(e: any) => setAssignUser(e.target.value)} />
              </Field>
              <Button disabled={busy} onClick={assign}>{t("dedip.assignBtn")}</Button>
            </div>
          </Card>

          <Card>
            <div className="nx-card-title" style={{ marginBottom: 12 }}>{t("dedip.poolTitle")}</div>
            {pool.loading ? (
              <SkeletonRows rows={4} cols={5} />
            ) : (pool.data?.items.length ?? 0) === 0 ? (
              <p className="nx-faint" style={{ fontSize: 13 }}>{t("dedip.empty")}</p>
            ) : (
              <div className="nx-table-wrap">
              <table className="nx-table">
                <thead>
                  <tr>
                    <th>{t("dedip.address")}</th>
                    <th>{t("dedip.nodeId")}</th>
                    <th>{t("dedip.assignedTo")}</th>
                    <th>{t("dedip.assignedAt")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {pool.data!.items.map((ip) => (
                    <tr key={ip.id}>
                      <td style={{ fontWeight: 600 }}>{ip.address}</td>
                      <td>{ip.node_id ?? "—"}</td>
                      <td>{ip.username ? <Pill tone="accent">{ip.username}</Pill> : <span className="nx-faint">{t("dedip.unassigned")}</span>}</td>
                      <td>{ip.assigned_at ? formatDate(ip.assigned_at) : "—"}</td>
                      <td style={{ textAlign: "right" }}>
                        {ip.username && (
                          <Button size="sm" variant="ghost" disabled={busy} onClick={() => release(ip.username)}>
                            {t("dedip.releaseBtn")}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
};
