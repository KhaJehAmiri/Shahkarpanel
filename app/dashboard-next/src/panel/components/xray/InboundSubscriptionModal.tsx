import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../../api/client";
import { Button, Callout, Field, Input, Modal, Toggle, useToast } from "../ui";

const normalizeHost = (v: string) => v.trim().toLowerCase().split(":")[0];
const normalizePath = (v: string) => v.trim().replace(/^\/+|\/+$/g, "");

interface EndpointInfo {
  id: number;
  slug: string;
  host: string | null;
  path_prefix: string;
  public_base_url: string;
  listen_port: number | null;
  inbound_tag: string | null;
  enabled: boolean;
}

interface SettingsResponse {
  inbound_tag: string;
  inherited: boolean;
  override: EndpointInfo | null;
  effective: EndpointInfo | null;
}

interface Props {
  inboundTag: string;
  onClose: () => void;
}

interface SslStatus {
  host: string;
  cert_present: boolean;
  https_ready: boolean;
  message: string;
  ok?: boolean;
}

export const InboundSubscriptionModal: FC<Props> = ({ inboundTag, onClose }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enablingSsl, setEnablingSsl] = useState(false);
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [ssl, setSsl] = useState<SslStatus | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [host, setHost] = useState("");
  const [listenPort, setListenPort] = useState("");
  const [pathPrefix, setPathPrefix] = useState("");
  const [publicBaseUrl, setPublicBaseUrl] = useState("");
  // A toast alone (auto-dismisses in ~4s) is easy to miss for a save that
  // was rejected — e.g. updating an existing override's domain to one
  // already claimed by another endpoint. Keep the reason visible in the
  // modal itself until the admin changes something or retries, so "why
  // didn't my change take effect" has an answer that doesn't disappear.
  const [saveError, setSaveError] = useState<{ message: string; tone: "error" | "info" } | null>(null);

  const refreshSsl = (tag: string) =>
    api
      .get<SslStatus>(`/inbounds/${encodeURIComponent(tag)}/subscription-endpoint/ssl`)
      .then(setSsl)
      .catch(() => setSsl(null));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<SettingsResponse>(`/inbounds/${encodeURIComponent(inboundTag)}/subscription-endpoint`)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        const src = res.override;
        setEnabled(!!src);
        setHost(src?.host || "");
        setListenPort(src?.listen_port != null ? String(src.listen_port) : "");
        setPathPrefix(src?.path_prefix || "");
        setPublicBaseUrl(src?.public_base_url || "");
        if (src?.host || res.effective?.host) {
          void refreshSsl(inboundTag);
        }
      })
      .catch((e: unknown) => toast.push(e instanceof Error ? e.message : t("common.error"), "error"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inboundTag]);

  const enableSsl = async () => {
    if (!host.trim() && !data?.override?.host && !data?.effective?.host) {
      toast.push(t("inboundSub.sslNeedDomain"), "error");
      return;
    }
    setEnablingSsl(true);
    try {
      const res = await api.post<SslStatus>(
        `/inbounds/${encodeURIComponent(inboundTag)}/subscription-endpoint/enable-ssl`,
        {},
      );
      setSsl(res);
      toast.push(t("inboundSub.sslEnabled"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("inboundSub.sslFailed"), "error");
    } finally {
      setEnablingSsl(false);
    }
  };

  const effective = data?.effective;

  // Prefill from the inherited panel endpoint as-is (path stays "sub").
  // Do NOT invent a unique path like "sub-<inboundTag>" — that was confusing
  // after 3x-ui migration where every inbound should keep /sub/ on the panel domain.
  const enableOverride = (on: boolean) => {
    setEnabled(on);
    if (on && data?.inherited && effective) {
      setHost(effective.host || "");
      setListenPort(effective.listen_port != null ? String(effective.listen_port) : "");
      setPathPrefix(effective.path_prefix || "sub");
      setPublicBaseUrl(effective.public_base_url || "");
    }
  };

  const duplicatesInherited = useMemo(() => {
    if (!enabled || !data?.inherited || !effective) return false;
    if (!pathPrefix.trim()) return false;
    const sameHost = normalizeHost(host || "") === (effective.host || "");
    const samePath = normalizePath(pathPrefix) === effective.path_prefix;
    return sameHost && samePath;
  }, [enabled, data, effective, host, pathPrefix]);

  const save = async () => {
    if (!pathPrefix.trim()) {
      toast.push(t("inboundSub.pathRequired"), "error");
      return;
    }
    setSaveError(null);
    setSaving(true);
    try {
      // Same domain+path as the shared panel endpoint → keep inheritance
      // (no dedicated override). Backend also treats this as success.
      if (duplicatesInherited) {
        if (data?.override) {
          await api.del(`/inbounds/${encodeURIComponent(inboundTag)}/subscription-endpoint`);
        }
        toast.push(t("inboundSub.usingInherited", { slug: effective?.slug }), "success");
        onClose();
        return;
      }
      const res = await api.put<SettingsResponse>(
        `/inbounds/${encodeURIComponent(inboundTag)}/subscription-endpoint`,
        {
          host: host.trim() || null,
          listen_port: listenPort.trim() ? Number(listenPort.trim()) : null,
          path_prefix: pathPrefix.trim(),
          public_base_url: publicBaseUrl.trim(),
          enabled: true,
        },
      );
      if (res.inherited && !res.override) {
        toast.push(t("inboundSub.usingInherited", { slug: res.effective?.slug || effective?.slug }), "success");
      } else {
        toast.push(t("inboundSub.saved"), "success");
      }
      onClose();
    } catch (e: unknown) {
      const alreadyInherited = e instanceof ApiError && !!e.body?.detail?.already_inherited;
      const message = e instanceof Error ? e.message : t("common.saveFailed");
      const tone = alreadyInherited ? "info" : "error";
      toast.push(message, tone);
      // Not saved — keep the reason visible in the modal (see saveError
      // above) rather than relying solely on the short-lived toast.
      setSaveError({ message, tone });
    } finally {
      setSaving(false);
    }
  };

  const clearOverride = async () => {
    if (!confirm(t("common.confirmDelete"))) return;
    setSaving(true);
    try {
      await api.del(`/inbounds/${encodeURIComponent(inboundTag)}/subscription-endpoint`);
      toast.push(t("inboundSub.cleared"), "success");
      onClose();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      title={t("inboundSub.title", { tag: inboundTag })}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          {data?.override && (
            <Button variant="danger" onClick={clearOverride} disabled={saving || loading}>
              {t("inboundSub.clearOverride")}
            </Button>
          )}
          <Button variant="primary" onClick={save} disabled={saving || loading || !enabled}>
            {saving ? t("common.loading") : t("common.save")}
          </Button>
        </>
      }
    >
      <p className="sk-faint" style={{ fontSize: 13, marginBottom: 12 }}>{t("inboundSub.desc")}</p>

      {loading ? (
        <div className="sk-faint">{t("common.loading")}</div>
      ) : (
        <>
          {data?.inherited && effective && (
            <div style={{ marginBottom: 14 }}>
              <Callout tone="info">
                {t("inboundSub.inheritedHint", {
                  slug: effective.slug,
                  host: effective.host || t("inboundSub.anyDomain"),
                  path: effective.path_prefix,
                })}
              </Callout>
            </div>
          )}

          <div className="sk-row" style={{ marginBottom: 14, gap: 10, alignItems: "center" }}>
            <Toggle on={enabled} onChange={(on) => { setSaveError(null); enableOverride(on); }} label={t("inboundSub.enableOverride")} />
          </div>

          {saveError && (
            <div style={{ marginBottom: 14 }}>
              <Callout tone={saveError.tone === "info" ? "info" : "danger"} title={t("inboundSub.notSaved")}>
                {saveError.message}
              </Callout>
            </div>
          )}

          <fieldset disabled={!enabled} style={{ border: 0, padding: 0, margin: 0, opacity: enabled ? 1 : 0.5 }}>
            <Field label={t("inboundSub.listenDomain")} hint={t("inboundSub.listenDomainHint")}>
              <Input
                dir="ltr"
                placeholder={t("inboundSub.listenDomainPlaceholder")}
                value={host}
                onChange={(e) => { setSaveError(null); setHost(e.target.value); }}
              />
            </Field>

            <Field label={t("inboundSub.listenPort")} hint={t("inboundSub.listenPortHint")}>
              <Input
                dir="ltr"
                type="number"
                min={1}
                max={65535}
                placeholder="2096"
                value={listenPort}
                onChange={(e) => { setSaveError(null); setListenPort(e.target.value); }}
              />
            </Field>

            <Field label={t("inboundSub.uriPath")} hint={t("inboundSub.uriPathHint")}>
              <Input
                dir="ltr"
                placeholder="sub"
                value={pathPrefix}
                onChange={(e) => { setSaveError(null); setPathPrefix(e.target.value); }}
              />
            </Field>

            <Field label={t("inboundSub.reverseProxyUri")} hint={t("inboundSub.reverseProxyUriHint")}>
              <Input
                dir="ltr"
                placeholder="https://panel.example.com:2096/sub"
                value={publicBaseUrl}
                onChange={(e) => { setSaveError(null); setPublicBaseUrl(e.target.value); }}
              />
            </Field>
          </fieldset>

          {(host.trim() || data?.override?.host || data?.effective?.host) && (
            <div style={{ marginTop: 16 }}>
              <Callout
                tone={ssl?.https_ready ? "ok" : "warn"}
                title={t("inboundSub.sslTitle")}
              >
                <div style={{ marginBottom: 10, fontSize: 13 }}>
                  {ssl?.https_ready
                    ? t("inboundSub.sslActive", { host: ssl.host })
                    : ssl?.message || t("inboundSub.sslHint")}
                </div>
                <Button
                  variant="primary"
                  onClick={enableSsl}
                  disabled={saving || loading || enablingSsl || !!ssl?.https_ready}
                >
                  {enablingSsl
                    ? t("inboundSub.sslEnabling")
                    : ssl?.https_ready
                      ? t("inboundSub.sslAlreadyOn")
                      : t("inboundSub.enableSsl")}
                </Button>
              </Callout>
            </div>
          )}

          {duplicatesInherited && effective && (
            <div style={{ marginTop: 12 }}>
              <Callout tone="info">
                {t("inboundSub.duplicatesInheritedHint", { slug: effective.slug })}
              </Callout>
            </div>
          )}
        </>
      )}
    </Modal>
  );
};
