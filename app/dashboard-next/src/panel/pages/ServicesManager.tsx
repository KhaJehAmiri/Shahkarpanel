import { FC, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { NodeItem } from "../api/types";
import { Button, Callout, Card, SkeletonRows, useToast } from "../components/ui";

type CatalogService = {
  slug: string;
  display_name: string;
  engine: string;
  protocol: string;
};

type NodeBinding = {
  service_slug: string;
  display_name: string;
  enabled: boolean;
};

export const ServicesManager: FC<{ embedded?: boolean }> = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [catalog, setCatalog] = useState<CatalogService[]>([]);
  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [bindings, setBindings] = useState<NodeBinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [svc, nd] = await Promise.all([
        api.get<CatalogService[]>("/services"),
        api.get<NodeItem[]>("/nodes"),
      ]);
      setCatalog(svc);
      setNodes(nd.filter((n) => n.status !== "disabled"));
      if (!selectedId && nd.length) setSelectedId(nd[0].id);
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setLoading(false);
    }
  }, [selectedId, t, toast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) return;
    api.get<NodeBinding[]>(`/node/${selectedId}/services`).then(setBindings).catch(() => setBindings([]));
  }, [selectedId]);

  const toggle = (slug: string) => {
    setBindings((prev) =>
      prev.map((b) => (b.service_slug === slug ? { ...b, enabled: !b.enabled } : b)),
    );
  };

  const save = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      const enabled = bindings.filter((b) => b.enabled).map((b) => b.service_slug);
      await api.put(`/node/${selectedId}/services`, { enabled });
      toast.push(t("services.saved"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Card><SkeletonRows rows={4} cols={2} /></Card>;

  return (
    <div className="sk-stack" style={{ gap: 16 }}>
      <Callout tone="info" title={t("services.hintTitle")}>{t("services.hintBody")}</Callout>

      <Card style={{ padding: 16 }}>
        <div className="sk-faint" style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>{t("services.catalogTitle")}</div>
        <div className="sk-row" style={{ gap: 8, flexWrap: "wrap" }}>
          {catalog.map((s) => (
            <span key={s.slug} className="sk-pill" style={{ fontSize: 12 }}>
              {s.display_name} <span className="sk-faint">({s.engine})</span>
            </span>
          ))}
        </div>
      </Card>

      <Card style={{ padding: 16 }}>
        <div className="sk-row" style={{ gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
          <label className="sk-label" style={{ margin: 0 }}>{t("services.pickNode")}</label>
          <select
            className="sk-input"
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(Number(e.target.value))}
          >
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>{n.name} ({n.address})</option>
            ))}
          </select>
          <div style={{ flex: 1 }} />
          <Button size="sm" variant="primary" disabled={saving || !selectedId} onClick={save}>
            {t("services.saveSync")}
          </Button>
        </div>

        <div className="sk-stack" style={{ gap: 8 }}>
          {bindings.map((b) => (
            <label key={b.service_slug} className="sk-row" style={{ gap: 8, cursor: "pointer" }}>
              <input type="checkbox" checked={b.enabled} onChange={() => toggle(b.service_slug)} />
              <span>{b.display_name}</span>
              <span className="sk-faint" style={{ fontSize: 11 }}>{b.service_slug}</span>
            </label>
          ))}
        </div>
      </Card>
    </div>
  );
};
