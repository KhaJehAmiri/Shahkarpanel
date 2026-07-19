import { FC, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { SudoOnly } from "../components/SudoGate";
import { SubscriptionEndpointEditModal } from "../components/subscription/SubscriptionEndpointEditModal";
import {
  groupPrimary,
  groupSubscriptionEndpoints,
  type EndpointChannel,
  type SubscriptionEndpointGroup,
  type SubscriptionEndpointRow,
} from "../components/subscription/types";
import { Button, Input, useToast } from "../components/ui";

export const SubscriptionEndpoints: FC = () => (
  <SudoOnly>
    <SubscriptionEndpointsInner />
  </SudoOnly>
);

const SubscriptionEndpointsInner: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [rows, setRows] = useState<SubscriptionEndpointRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<{
    group: SubscriptionEndpointGroup;
    tab?: EndpointChannel;
  } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<SubscriptionEndpointRow[]>("/subscription-endpoints")
      .then(setRows)
      .catch((e: unknown) => toast.push(e instanceof Error ? e.message : t("common.error"), "error"))
      .finally(() => setLoading(false));
  }, [t, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const groups = useMemo(() => groupSubscriptionEndpoints(rows), [rows]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return groups;
    return groups.filter((g) => {
      const primary = groupPrimary(g);
      const blob = [
        g.label,
        g.key,
        primary?.host || "",
        g.main?.path_prefix || "",
        g.json?.path_prefix || "",
        g.clash?.path_prefix || "",
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(needle);
    });
  }, [groups, q]);

  const applyUpdates = (updated: SubscriptionEndpointRow[]) => {
    setRows((prev) => {
      const map = new Map(updated.map((u) => [u.id, u]));
      return prev.map((r) => map.get(r.id) || r);
    });
  };

  return (
    <div className="nx-sub-ep">
      <div className="nx-sub-ep-hero">
        <div>
          <h3 className="nx-sub-ep-hero-title">{t("subEndpoints.hintTitle")}</h3>
          <p className="nx-sub-ep-hero-body">{t("subEndpoints.hintBodyCompact")}</p>
        </div>
        <div className="nx-sub-ep-hero-meta" dir="ltr">
          <span>{filtered.length}</span>
          <small>{t("subEndpoints.panelCount")}</small>
        </div>
      </div>

      <div className="nx-sub-ep-toolbar">
        <Input
          dir="ltr"
          placeholder={t("subEndpoints.searchPlaceholder")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="nx-sub-ep-search"
        />
        <Button variant="ghost" onClick={load} disabled={loading}>
          {t("common.refresh")}
        </Button>
      </div>

      {loading ? (
        <div className="nx-faint">{t("common.loading")}</div>
      ) : filtered.length === 0 ? (
        <div className="nx-faint">{t("common.noData")}</div>
      ) : (
        <div className="nx-sub-ep-grid-cards">
          {filtered.map((g) => {
            const primary = groupPrimary(g);
            const host = primary?.host || t("inboundSub.anyDomain");
            const port = primary?.listen_port;
            const channels: { id: EndpointChannel; ep: SubscriptionEndpointRow | null }[] = [
              { id: "main", ep: g.main },
              { id: "json", ep: g.json },
              { id: "clash", ep: g.clash },
            ];
            const present = channels.filter((c) => c.ep);
            const allOn = present.every((c) => c.ep!.enabled);
            return (
              <article key={g.key} className="nx-sub-ep-card">
                <header className="nx-sub-ep-card-head">
                  <div>
                    <div className="nx-sub-ep-card-title" dir="ltr">
                      {g.label}
                    </div>
                    <div className="nx-sub-ep-card-host" dir="ltr">
                      {host}
                      {port != null ? `:${port}` : ""}
                    </div>
                  </div>
                  <span className={`nx-sub-ep-pill ${allOn ? "is-on" : "is-off"}`}>
                    {allOn ? t("common.enabled") : t("common.disabled")}
                  </span>
                </header>

                <div className="nx-sub-ep-channels">
                  {present.map(({ id, ep }) => (
                    <button
                      key={id}
                      type="button"
                      className="nx-sub-ep-chip"
                      dir="ltr"
                      onClick={() => setEditing({ group: g, tab: id })}
                      title={t("subEndpoints.editChannel", { kind: t(`subEndpoints.kind.${id}`) })}
                    >
                      <span className="nx-sub-ep-chip-kind">{t(`subEndpoints.kind.${id}`)}</span>
                      <span className="nx-sub-ep-chip-path">/{ep!.path_prefix}/</span>
                      {!ep!.enabled && <span className="nx-sub-ep-chip-off">off</span>}
                    </button>
                  ))}
                  {g.extras.map((ep) => (
                    <span key={ep.id} className="nx-sub-ep-chip is-static" dir="ltr">
                      <span className="nx-sub-ep-chip-kind">{ep.slug}</span>
                      <span className="nx-sub-ep-chip-path">/{ep.path_prefix}/</span>
                    </span>
                  ))}
                </div>

                <footer className="nx-sub-ep-card-foot">
                  <span className="nx-faint" style={{ fontSize: 12 }}>
                    {t("subEndpoints.channelCount", { count: present.length + g.extras.length })}
                  </span>
                  <Button size="sm" variant="primary" onClick={() => setEditing({ group: g })}>
                    {t("common.edit")}
                  </Button>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {editing && (
        <SubscriptionEndpointEditModal
          group={editing.group}
          initialTab={editing.tab}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            applyUpdates(updated);
            if (updated.length > 1) setEditing(null);
          }}
        />
      )}
    </div>
  );
};
