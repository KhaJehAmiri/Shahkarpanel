import { ChangeEvent, FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import { Button, Callout, Field, Input, Modal, Pill, useToast } from "../ui";

type WarpAccountView = {
  tag?: string;
  registered?: boolean;
  device_id?: string;
  license_key?: string;
  account_type?: string;
  warp_plus?: boolean;
  premium_data?: number;
  quota?: number;
  outbound?: Record<string, unknown>;
};

type WarpStore = {
  registered: boolean;
  default?: string | null;
  accounts?: Record<string, WarpAccountView>;
};

function suggestWarpTag(existing: string[]): string {
  if (!existing.includes("warp")) return "warp";
  let n = 2;
  while (existing.includes(`warp-${n}`)) n += 1;
  return `warp-${n}`;
}

export const WarpDialog: FC<{
  outbounds: Record<string, unknown>[];
  onClose: () => void;
  onAddOutbound: (outbound: Record<string, unknown>) => void;
  onConfigSynced?: (config: Record<string, unknown>) => void;
}> = ({ outbounds, onClose, onAddOutbound, onConfigSynced }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [store, setStore] = useState<WarpStore | null>(null);
  const [selectedTag, setSelectedTag] = useState("warp");
  const [newTag, setNewTag] = useState("warp");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [license, setLicense] = useState("");

  const accountTags = useMemo(
    () => Object.keys(store?.accounts || {}).sort(),
    [store],
  );

  const account = store?.accounts?.[selectedTag] || null;

  const syncConfigFromServer = async () => {
    if (!onConfigSynced) return;
    try {
      const cfg = await api.get<Record<string, unknown>>("/core/config");
      onConfigSynced(cfg);
    } catch {
      /* parent still has stale outbound until refresh */
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.get<WarpStore>("/core/warp");
      setStore(data);
      const tags = Object.keys(data.accounts || {});
      const pick = data.default && tags.includes(data.default)
        ? data.default
        : tags[0] || "warp";
      setSelectedTag(pick);
      setNewTag(suggestWarpTag(tags));
      const acct = data.accounts?.[pick];
      setLicense(acct?.license_key || "");
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("warp.loadFailed"), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (account) setLicense(account.license_key || "");
  }, [selectedTag, account?.license_key]);

  const selectTag = (tag: string) => {
    setSelectedTag(tag);
    const acct = store?.accounts?.[tag];
    setLicense(acct?.license_key || "");
  };

  const register = async (tagOverride?: string) => {
    const tag = (tagOverride || newTag || "warp").trim().replace(/,/g, "");
    if (!tag) {
      toast.push(t("warp.tagRequired"), "error");
      return;
    }
    setBusy(true);
    try {
      await api.post<WarpAccountView>("/core/warp/register", { tag });
      toast.push(t("warp.registered"), "success");
      await load();
      setSelectedTag(tag);
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("warp.registerFailed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const applyLicense = async () => {
    if (!license.trim() || !selectedTag) return;
    setBusy(true);
    try {
      await api.post<WarpAccountView>("/core/warp/license", {
        license: license.trim(),
        tag: selectedTag,
      });
      toast.push(t("warp.licenseApplied"), "success");
      await load();
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("warp.licenseFailed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!selectedTag || !confirm(t("warp.confirmDeleteTag", { tag: selectedTag }))) return;
    setBusy(true);
    try {
      await api.del(`/core/warp/${encodeURIComponent(selectedTag)}`);
      toast.push(t("warp.deleted"), "success");
      await load();
      await syncConfigFromServer();
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const removeAll = async () => {
    if (!confirm(t("warp.confirmDeleteAll"))) return;
    setBusy(true);
    try {
      await api.del("/core/warp");
      toast.push(t("warp.deletedAll"), "success");
      await load();
      await syncConfigFromServer();
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const addToConfig = () => {
    if (!account?.outbound) return;
    onAddOutbound(account.outbound);
  };

  const warpTag = String(account?.outbound?.tag || account?.tag || selectedTag || "warp");
  const alreadyAdded = outbounds.some((o) => String(o.tag) === warpTag);
  const isPlus =
    Boolean(account?.warp_plus) ||
    (account?.account_type && account.account_type !== "free") ||
    (account?.premium_data ?? 0) > 0;
  const hasAccounts = accountTags.length > 0;

  return (
    <Modal
      open
      title={t("warp.title")}
      onClose={onClose}
      footer={<Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>}
    >
      <div className="nx-stack" style={{ gap: 16 }}>
        <Callout tone="info" title={t("warp.aboutTitle")}>{t("warp.aboutMulti")}</Callout>

        {loading ? (
          <div style={{ color: "var(--nx-muted)" }}>{t("common.loading")}</div>
        ) : (
          <>
            <Field label={t("warp.newTag")} hint={t("warp.newTagHint")}>
              <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
                <Input
                  value={newTag}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setNewTag(e.target.value)}
                  placeholder="warp-2"
                  className="nx-mono"
                  dir="ltr"
                  style={{ maxWidth: 160 }}
                />
                <Button variant="primary" onClick={() => register()} disabled={busy}>
                  {busy ? t("warp.registering") : t("warp.registerNew")}
                </Button>
              </div>
            </Field>

            {!hasAccounts ? (
              <Callout tone="warn">{t("warp.notRegistered")}</Callout>
            ) : (
              <>
                <Field label={t("warp.accounts")}>
                  <div className="nx-row" style={{ gap: 6, flexWrap: "wrap" }}>
                    {accountTags.map((tag) => (
                      <Button
                        key={tag}
                        size="sm"
                        variant={tag === selectedTag ? "primary" : "ghost"}
                        onClick={() => selectTag(tag)}
                      >
                        {tag}
                        {store?.default === tag ? ` · ${t("warp.default")}` : ""}
                      </Button>
                    ))}
                  </div>
                </Field>

                {account && (
                  <>
                    <div className="nx-row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <Pill tone="ok" dot>{t("warp.statusActive")}</Pill>
                      <Pill tone={isPlus ? "accent" : "default"}>{isPlus ? "WARP+" : "WARP free"}</Pill>
                      <Pill tone="default">{warpTag}</Pill>
                    </div>

                    <Field label={t("warp.deviceId")}>
                      <Input value={account.device_id || ""} readOnly className="nx-mono" dir="ltr" />
                    </Field>

                    <Field label={t("warp.license")} hint={t("warp.licenseHint")}>
                      <div className="nx-row" style={{ gap: 8, flexWrap: "wrap" }}>
                        <Input
                          value={license}
                          onChange={(e: ChangeEvent<HTMLInputElement>) => setLicense(e.target.value)}
                          placeholder="xxxxxxxx-xxxx-xxxx"
                          className="nx-mono"
                          dir="ltr"
                        />
                        <Button onClick={applyLicense} disabled={busy || !license.trim()}>
                          {t("warp.applyLicense")}
                        </Button>
                      </div>
                    </Field>

                    {alreadyAdded ? (
                      <Callout tone="ok">{t("warp.outboundPresent", { tag: warpTag })}</Callout>
                    ) : (
                      <Callout tone="warn">{t("warp.outboundMissing")}</Callout>
                    )}

                    <div className="nx-row" style={{ gap: 8, flexWrap: "wrap", justifyContent: "space-between" }}>
                      <div className="nx-row" style={{ gap: 8 }}>
                        <Button variant="danger" onClick={remove} disabled={busy}>
                          {t("warp.deleteTag")}
                        </Button>
                        {accountTags.length > 1 && (
                          <Button variant="ghost" onClick={removeAll} disabled={busy}>
                            {t("warp.deleteAll")}
                          </Button>
                        )}
                      </div>
                      <Button variant="primary" onClick={addToConfig} disabled={busy}>
                        {alreadyAdded ? t("warp.updateOutbound") : t("warp.addOutbound")}
                      </Button>
                    </div>
                  </>
                )}
              </>
            )}
          </>
        )}
      </div>
    </Modal>
  );
};
