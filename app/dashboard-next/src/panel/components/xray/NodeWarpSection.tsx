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

type WarpMode = "sensitive" | "full";

function parseTags(raw: string | null | undefined, fallback: string): string[] {
  const parts = String(raw || "")
    .split(/[,;]/)
    .map((s) => s.trim())
    .filter(Boolean);
  return parts.length ? parts : [fallback];
}

export const NodeWarpSection: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const nodes = useFetch<NodeItem[]>(() => api.get("/nodes"), []);
  const warp = useFetch<WarpStore>(() => api.get("/core/warp"), []);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [draftTags, setDraftTags] = useState<Record<number, string[]>>({});
  const [draftMode, setDraftMode] = useState<Record<number, WarpMode>>({});

  const tags = useMemo(() => {
    const keys = Object.keys(warp.data?.accounts || {});
    if (!keys.length) return ["warp"];
    return keys;
  }, [warp.data]);

  const eligibleNodes = useMemo(() => {
    return (nodes.data || []).filter((n) => n.status !== "disabled");
  }, [nodes.data]);

  const tagsFor = (n: NodeItem) =>
    draftTags[n.id] || parseTags(n.warp_tag, tags[0] || "warp");
  const modeFor = (n: NodeItem): WarpMode =>
    draftMode[n.id] || (n.warp_mode === "full" ? "full" : "sensitive");

  const apply = async (
    node: NodeItem,
    enabled: boolean,
    selected: string[],
    mode: WarpMode,
  ) => {
    const tag = (selected.length ? selected : [tags[0] || "warp"]).join(",");
    setBusyId(node.id);
    try {
      await api.put(`/node/${node.id}/warp`, { enabled, tag, mode });
      toast.push(
        enabled
          ? t("warp.nodeEnabled", { name: node.name, tag, mode })
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

  const toggleTag = (node: NodeItem, tag: string, mode: WarpMode, enabled: boolean) => {
    const current = tagsFor(node);
    const next = current.includes(tag)
      ? current.filter((x) => x !== tag)
      : [...current, tag];
    const resolved = next.length ? next : [tag];
    setDraftTags((prev) => ({ ...prev, [node.id]: resolved }));
    if (enabled) void apply(node, true, resolved, mode);
  };

  const kindLabel = (n: NodeItem) => {
    const kind = n.core_kind || "xray";
    return kind === "wireguard" ? "WireGuard + Xray" : "Xray";
  };

  const statusPill = (n: NodeItem) => {
    if (!n.warp_enabled) return <Pill tone="default">{t("warp.nodeOff")}</Pill>;
    if (n.warp_mode === "full") return <Pill tone="warn" dot>{t("warp.modeFullShort")}</Pill>;
    return <Pill tone="ok" dot>{t("warp.modeSensitiveShort")}</Pill>;
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
                  <th>{t("warp.modeLabel")}</th>
                  <th>{t("warp.newTag")}</th>
                  <th className="sk-actions">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {eligibleNodes.map((n) => {
                  const enabled = Boolean(n.warp_enabled);
                  const selected = tagsFor(n);
                  const mode = modeFor(n);
                  const busy = busyId === n.id;
                  return (
                    <tr key={n.id}>
                      <td>
                        <div className="sk-proto-name">
                          <span className="sk-proto-name-main">{n.name}</span>
                          <span className="sk-proto-name-sub">{kindLabel(n)}</span>
                        </div>
                      </td>
                      <td>{statusPill(n)}</td>
                      <td style={{ minWidth: 150 }}>
                        <Select
                          value={mode}
                          disabled={busy}
                          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
                            const next = e.target.value as WarpMode;
                            setDraftMode((prev) => ({ ...prev, [n.id]: next }));
                            if (enabled) void apply(n, true, selected, next);
                          }}
                        >
                          <option value="sensitive">{t("warp.modeSensitive")}</option>
                          <option value="full">{t("warp.modeFull")}</option>
                        </Select>
                      </td>
                      <td style={{ minWidth: 180 }}>
                        {mode === "sensitive" && tags.length > 1 ? (
                          <div className="sk-stack" style={{ gap: 4 }}>
                            {tags.map((tg) => (
                              <label
                                key={tg}
                                style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}
                              >
                                <input
                                  type="checkbox"
                                  disabled={busy}
                                  checked={selected.includes(tg)}
                                  onChange={() => toggleTag(n, tg, mode, enabled)}
                                />
                                {tg}
                              </label>
                            ))}
                            <div className="sk-faint" style={{ fontSize: 11 }}>
                              {t("warp.multiTagHint")}
                            </div>
                          </div>
                        ) : (
                          <Select
                            value={selected[0] || tags[0]}
                            disabled={busy || !tags.length}
                            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
                              const next = [e.target.value];
                              setDraftTags((prev) => ({ ...prev, [n.id]: next }));
                              if (enabled) void apply(n, true, next, mode);
                            }}
                          >
                            {tags.map((tg) => (
                              <option key={tg} value={tg}>{tg}</option>
                            ))}
                          </Select>
                        )}
                      </td>
                      <td className="sk-actions">
                        {enabled ? (
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() => void apply(n, false, selected, mode)}
                          >
                            {t("common.disable")}
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={busy || !Object.keys(warp.data?.accounts || {}).length}
                            onClick={() => void apply(n, true, selected, mode)}
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
