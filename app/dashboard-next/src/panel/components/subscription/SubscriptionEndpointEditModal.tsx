import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../../api/client";
import { Button, Callout, Field, Input, Modal, Tabs, Toggle, useToast } from "../ui";
import type {
  EndpointChannel,
  SubscriptionEndpointGroup,
  SubscriptionEndpointRow,
} from "./types";

interface SslStatus {
  host: string;
  cert_present: boolean;
  https_ready: boolean;
  message: string;
  ok?: boolean;
}

interface ChannelForm {
  id: number;
  slug: string;
  enabled: boolean;
  host: string;
  listenPort: string;
  pathPrefix: string;
  publicBaseUrl: string;
}

interface Props {
  group: SubscriptionEndpointGroup;
  initialTab?: EndpointChannel;
  onClose: () => void;
  onSaved: (updated: SubscriptionEndpointRow[]) => void;
}

const samplePreview = (host: string, port: string, path: string) => {
  const h = host.trim() || "example.com";
  const p = (path || "sub").replace(/^\/+|\/+$/g, "") || "sub";
  const portNum = port.trim() ? Number(port.trim()) : null;
  if (portNum && portNum !== 443 && portNum !== 80) {
    return `https://${h}:${portNum}/${p}/<token>/`;
  }
  return `https://${h}/${p}/<token>/`;
};

function toForm(ep: SubscriptionEndpointRow): ChannelForm {
  return {
    id: ep.id,
    slug: ep.slug,
    enabled: ep.enabled,
    host: ep.host || "",
    listenPort: ep.listen_port != null ? String(ep.listen_port) : "",
    pathPrefix: ep.path_prefix || "",
    publicBaseUrl: ep.public_base_url || "",
  };
}

export const SubscriptionEndpointEditModal: FC<Props> = ({
  group,
  initialTab,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const channels = useMemo(() => {
    const list: { id: EndpointChannel; ep: SubscriptionEndpointRow }[] = [];
    if (group.main) list.push({ id: "main", ep: group.main });
    if (group.json) list.push({ id: "json", ep: group.json });
    if (group.clash) list.push({ id: "clash", ep: group.clash });
    // Lone extras (no main/json/clash) — show as a single Main tab.
    if (!list.length && group.extras[0]) {
      list.push({ id: "main", ep: group.extras[0] });
    }
    return list;
  }, [group]);

  const [tab, setTab] = useState<EndpointChannel>(
    initialTab && channels.some((c) => c.id === initialTab)
      ? initialTab
      : channels[0]?.id || "main",
  );
  const [forms, setForms] = useState<Record<number, ChannelForm>>(() => {
    const init: Record<number, ChannelForm> = {};
    for (const c of channels) init[c.ep.id] = toForm(c.ep);
    return init;
  });
  const [saving, setSaving] = useState(false);
  const [enablingSsl, setEnablingSsl] = useState(false);
  const [ssl, setSsl] = useState<SslStatus | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const active = channels.find((c) => c.id === tab) || channels[0];
  const form = active ? forms[active.ep.id] : null;

  const refreshSsl = (id: number) =>
    api
      .get<SslStatus>(`/subscription-endpoints/${id}/ssl`)
      .then(setSsl)
      .catch(() => setSsl(null));

  useEffect(() => {
    if (active?.ep.host) void refreshSsl(active.ep.id);
    else setSsl(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.ep.id, active?.ep.host]);

  const preview = useMemo(() => {
    if (!form) return "";
    return samplePreview(form.host, form.listenPort, form.pathPrefix);
  }, [form]);

  const patchForm = (id: number, patch: Partial<ChannelForm>) => {
    setSaveError(null);
    setForms((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  };

  const saveCurrent = async () => {
    if (!form || !active) return;
    if (!form.pathPrefix.trim()) {
      toast.push(t("inboundSub.pathRequired"), "error");
      return;
    }
    setSaveError(null);
    setSaving(true);
    try {
      const res = await api.put<SubscriptionEndpointRow>(`/subscription-endpoints/${form.id}`, {
        host: form.host.trim() || null,
        listen_port: form.listenPort.trim() ? Number(form.listenPort.trim()) : null,
        path_prefix: form.pathPrefix.trim().replace(/^\/+|\/+$/g, ""),
        public_base_url: form.publicBaseUrl.trim(),
        enabled: form.enabled,
      });
      toast.push(t("subEndpoints.saved"), "success");
      onSaved([res]);
    } catch (e: unknown) {
      const message = e instanceof ApiError || e instanceof Error ? e.message : t("common.saveFailed");
      toast.push(message, "error");
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  };

  const saveAll = async () => {
    setSaveError(null);
    setSaving(true);
    const updated: SubscriptionEndpointRow[] = [];
    try {
      for (const c of channels) {
        const f = forms[c.ep.id];
        if (!f?.pathPrefix.trim()) {
          throw new Error(t("inboundSub.pathRequired"));
        }
        const res = await api.put<SubscriptionEndpointRow>(`/subscription-endpoints/${f.id}`, {
          host: f.host.trim() || null,
          listen_port: f.listenPort.trim() ? Number(f.listenPort.trim()) : null,
          path_prefix: f.pathPrefix.trim().replace(/^\/+|\/+$/g, ""),
          public_base_url: f.publicBaseUrl.trim(),
          enabled: f.enabled,
        });
        updated.push(res);
      }
      toast.push(t("subEndpoints.savedAll"), "success");
      onSaved(updated);
      onClose();
    } catch (e: unknown) {
      const message = e instanceof ApiError || e instanceof Error ? e.message : t("common.saveFailed");
      toast.push(message, "error");
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  };

  const enableSsl = async () => {
    if (!form) return;
    if (!form.host.trim()) {
      toast.push(t("inboundSub.sslNeedDomain"), "error");
      return;
    }
    setEnablingSsl(true);
    try {
      await api.put(`/subscription-endpoints/${form.id}`, {
        host: form.host.trim(),
        path_prefix: form.pathPrefix.trim().replace(/^\/+|\/+$/g, "") || active!.ep.path_prefix,
      });
      const res = await api.post<SslStatus>(`/subscription-endpoints/${form.id}/enable-ssl`, {});
      setSsl(res);
      toast.push(t("inboundSub.sslEnabled"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("inboundSub.sslFailed"), "error");
    } finally {
      setEnablingSsl(false);
    }
  };

  const tabItems = channels.map((c) => ({
    id: c.id,
    label: t(`subEndpoints.kind.${c.id}`),
  }));

  return (
    <Modal
      open
      wide
      title={t("subEndpoints.editTitle", { slug: group.label })}
      onClose={onClose}
      className="nx-sub-ep-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          {channels.length > 1 && (
            <Button variant="ghost" onClick={saveCurrent} disabled={saving || !form}>
              {saving ? t("common.loading") : t("subEndpoints.saveTab")}
            </Button>
          )}
          <Button variant="primary" onClick={channels.length > 1 ? saveAll : saveCurrent} disabled={saving || !form}>
            {saving ? t("common.loading") : channels.length > 1 ? t("subEndpoints.saveAll") : t("common.save")}
          </Button>
        </>
      }
    >
      <p className="nx-faint" style={{ fontSize: 13, marginBottom: 14 }}>
        {t("subEndpoints.editDescGrouped")}
      </p>

      {tabItems.length > 1 && (
        <Tabs
          active={tab}
          onChange={(id) => setTab(id as EndpointChannel)}
          tabs={tabItems}
        />
      )}

      {saveError && (
        <div style={{ marginBottom: 14 }}>
          <Callout tone="danger" title={t("inboundSub.notSaved")}>
            {saveError}
          </Callout>
        </div>
      )}

      {!form || !active ? (
        <div className="nx-faint">{t("common.noData")}</div>
      ) : (
        <div className="nx-sub-ep-form">
          <div className="nx-sub-ep-form-head">
            <div>
              <div className="nx-sub-ep-channel">{t(`subEndpoints.kind.${active.id}`)}</div>
              <code className="nx-sub-ep-slug" dir="ltr">
                {form.slug}
              </code>
            </div>
            <label className="nx-sub-ep-toggle">
              <Toggle
                on={form.enabled}
                onChange={(on) => patchForm(form.id, { enabled: on })}
                label={t("subEndpoints.enabled")}
              />
              <span>{t("subEndpoints.enabled")}</span>
            </label>
          </div>

          <div className="nx-sub-ep-grid">
            <Field label={t("inboundSub.listenDomain")} hint={t("inboundSub.listenDomainHint")}>
              <Input
                dir="ltr"
                placeholder={t("inboundSub.listenDomainPlaceholder")}
                value={form.host}
                onChange={(e) => patchForm(form.id, { host: e.target.value })}
              />
            </Field>
            <Field label={t("inboundSub.listenPort")} hint={t("inboundSub.listenPortHint")}>
              <Input
                dir="ltr"
                type="number"
                min={1}
                max={65535}
                placeholder="2096"
                value={form.listenPort}
                onChange={(e) => patchForm(form.id, { listenPort: e.target.value })}
              />
            </Field>
          </div>

          <Field label={t("inboundSub.uriPath")} hint={t("inboundSub.uriPathHint")}>
            <Input
              dir="ltr"
              placeholder={active.id === "json" ? "json" : active.id === "clash" ? "clash" : "sub"}
              value={form.pathPrefix}
              onChange={(e) => patchForm(form.id, { pathPrefix: e.target.value })}
            />
          </Field>

          <Field label={t("inboundSub.reverseProxyUri")} hint={t("inboundSub.reverseProxyUriHint")}>
            <Input
              dir="ltr"
              placeholder="https://panel.example.com:2096/sub"
              value={form.publicBaseUrl}
              onChange={(e) => patchForm(form.id, { publicBaseUrl: e.target.value })}
            />
          </Field>

          <div className="nx-sub-ep-preview">
            <div className="nx-sub-ep-preview-label">{t("subEndpoints.previewTitle")}</div>
            <code dir="ltr">{preview}</code>
          </div>

          {form.host.trim() && (
            <div className="nx-sub-ep-ssl">
              <div className="nx-sub-ep-ssl-text">
                <strong>{t("inboundSub.sslTitle")}</strong>
                <span>
                  {ssl?.https_ready
                    ? t("inboundSub.sslActive", { host: ssl.host })
                    : ssl?.message || t("inboundSub.sslHint")}
                </span>
              </div>
              <Button
                variant={ssl?.https_ready ? "ghost" : "primary"}
                onClick={enableSsl}
                disabled={saving || enablingSsl || !!ssl?.https_ready}
              >
                {enablingSsl
                  ? t("inboundSub.sslEnabling")
                  : ssl?.https_ready
                    ? t("inboundSub.sslAlreadyOn")
                    : t("inboundSub.enableSsl")}
              </Button>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};
