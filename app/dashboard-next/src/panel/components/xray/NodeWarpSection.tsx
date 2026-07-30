import { FC, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import type { NodeItem } from "../../api/types";
import { useFetch } from "../../lib/useFetch";
import { Button, Callout, Card, EmptyState, Pill, Select, useToast } from "../ui";

type WarpStore = {
  registered?: boolean;
  default?: string | null;
  accounts?: Record<string, { tag?: string }>;
};

export const NodeWarpSection: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const warp = useFetch<WarpStore>(() => api.get("/core/warp"), []);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [draftTag, setDraftTag] = useState<Record<number, string>>({});

  const tags = useMemo(() => {
    const keys = Object.keys(warp.data?.accounts || {});
    if (!keys.length) return ["warp"];
    return keys;
  }, [warp.data]);

  const eligibleNodes = useMemo(() => {
    // WARP is injected via build_node_xray_config, which also runs on
    // wireguard-core nodes that still host an Xray agent (e.g. xray_wg).
    return (nodes.data || []).filter((n) => n.status !== "disabled");
  }, [nodes.data]);

  const tagFor = (n: NodeItem) => draftTag[n.id] || n.warp_tag || tags[0] || "warp";

  const apply = async (node: NodeItem, enabled: boolean, tag: string) => {
    setBusyId(node.id);
    try {
      await api.put(`/node/${node.id}/warp`, { enabled, tag });
      toast.push(
        enabled
          ? t("warp.nodeEnabled", { name: node.name, tag })
          : t("warp.nodeDisabled", { name: node.name }),
        "success",
      );
      nodes.reload();
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : String(e), "error");
    } finally {
      setBusyId(null);
    }
  };

  const kindLabel = (n: NodeItem) => {
    const kind = n.core_kind || "xray";
    return kind === "wireguard" ? "WireGuard + Xray" : "Xray";
  };

  return (
    <Card>
      <div className="sk-stack" style={{ gap: 12 }}>
        <div>
          <div style={{ fontWeight: 600 }}>{t("warp.nodeSectionTitle")}</div>
          <div className="sk-faint" style={{ fontSize: 12, marginTop: 4 }}>
            {t("warp.nodeSectionDesc")}
          </div>
        </div>
        {!Object.keys(warp.data?.accounts || {}).length && (
          <Callout tone="warn">{t("warp.nodeNeedAccount")}</Callout>
        )}
        {nodes.loading ? (
          <div className="sk-faint">{t("common.loading")}</div>
        ) : !eligibleNodes.length ? (
          <EmptyState title={t("common.noData")} desc={t("warp.nodeEmpty")} />
        ) : (
          <div className="sk-table-wrap">
            <table className="sk-table">
              <thead>
                <tr>
                  <th>{t("common.name")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("warp.newTag")}</th>
                  <th className="sk-actions">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {eligibleNodes.map((n) => {
                  const enabled = Boolean(n.warp_enabled);
                  const tag = tagFor(n);
                  const busy = busyId === n.id;
                  return (
                    <tr key={n.id}>
                      <td>
                        <div className="sk-proto-name">
                          <span className="sk-proto-name-main">{n.name}</span>
                          <span className="sk-proto-name-sub">{kindLabel(n)}</span>
                        </div>
                      </td>
                      <td>
                        {enabled ? (
                          <Pill tone="ok" dot>{t("warp.nodeOn")}</Pill>
                        ) : (
                          <Pill tone="default">{t("warp.nodeOff")}</Pill>
                        )}
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <Select
                          value={tag}
                          disabled={busy || !tags.length}
                          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
                            const next = e.target.value;
                            setDraftTag((prev) => ({ ...prev, [n.id]: next }));
                            if (enabled) void apply(n, true, next);
                          }}
                        >
                          {tags.map((tg) => (
                            <option key={tg} value={tg}>{tg}</option>
                          ))}
                        </Select>
                      </td>
                      <td className="sk-actions">
                        {enabled ? (
                          <Button size="sm" disabled={busy} onClick={() => void apply(n, false, tag)}>
                            {t("common.disable")}
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={busy || !Object.keys(warp.data?.accounts || {}).length}
                            onClick={() => void apply(n, true, tag)}
                          >
                            {t("warp.enableOnNode")}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
};
