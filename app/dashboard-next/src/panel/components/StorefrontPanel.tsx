import React, { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useFetch } from "../lib/useFetch";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, SkeletonRows, Textarea, Toggle, useToast,
} from "./ui";

type StorefrontMine = {
  invite_code: string;
  public_signup_enabled: boolean;
  reseller_apply_enabled: boolean;
  storefront_headline?: string | null;
  storefront_tagline?: string | null;
  tenant_slug?: string | null;
  storefront_enabled: boolean;
  effective_signup_enabled: boolean;
  effective_reseller_apply_enabled: boolean;
  links: {
    landing: string;
    register: string;
    become_reseller: string;
    portal: string;
  };
  branding: {
    panel_title?: string | null;
    domain?: string | null;
    panel_url?: string | null;
  };
};

type ApplicationRow = {
  id: number;
  username: string;
  display_name?: string | null;
  contact?: string | null;
  message?: string | null;
  status: string;
  created_at?: string | null;
  reject_reason?: string | null;
};

function absLink(path: string): string {
  if (typeof window === "undefined") return path;
  try {
    return new URL(path, window.location.origin).toString();
  } catch {
    return path;
  }
}

export const StorefrontPanel: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, error, reload } = useFetch<StorefrontMine>(
    () => api.get("/storefront/mine"),
    [],
  );
  const apps = useFetch<ApplicationRow[]>(
    () => api.get("/storefront/applications?status=pending"),
    [],
  );
  const [headline, setHeadline] = useState<string | null>(null);
  const [tagline, setTagline] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (loading) return <Card><SkeletonRows rows={6} cols={2} /></Card>;
  if (error || !data) return <EmptyState title={t("common.error")} desc={error || ""} />;

  const h = headline ?? data.storefront_headline ?? "";
  const tg = tagline ?? data.storefront_tagline ?? "";

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.push(t("common.copied", { defaultValue: "Copied" }), "success");
    } catch {
      toast.push(text, "info");
    }
  };

  const save = async (patch: Partial<StorefrontMine>) => {
    setBusy(true);
    try {
      await api.put("/storefront/mine", {
        public_signup_enabled: patch.public_signup_enabled ?? data.public_signup_enabled,
        reseller_apply_enabled: patch.reseller_apply_enabled ?? data.reseller_apply_enabled,
        storefront_headline: patch.storefront_headline ?? h,
        storefront_tagline: patch.storefront_tagline ?? tg,
      });
      toast.push(t("common.saved"), "success");
      setHeadline(null);
      setTagline(null);
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const rotate = async () => {
    setBusy(true);
    try {
      await api.post("/storefront/mine/rotate-invite", {});
      toast.push(t("storefront.inviteRotated"), "success");
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const approve = async (id: number) => {
    try {
      await api.post(`/storefront/applications/${id}/approve`, {});
      toast.push(t("storefront.approved"), "success");
      apps.reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const reject = async (id: number) => {
    try {
      await api.post(`/storefront/applications/${id}/reject`, { reason: "" });
      toast.push(t("storefront.rejected"), "success");
      apps.reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    }
  };

  const landingUrl = absLink(data.links.landing);
  const registerUrl = absLink(data.links.register);
  const becomeUrl = absLink(data.links.become_reseller);

  return (
    <div className="sk-stack" style={{ gap: 20 }}>
      {!data.storefront_enabled && (
        <Callout tone="warn">{t("storefront.platformOff")}</Callout>
      )}
      <Card>
        <CardHead title={t("storefront.settingsTitle")} />
        <div className="sk-stack" style={{ gap: 14 }}>
          <div className="sk-row" style={{ justifyContent: "space-between" }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{t("storefront.publicSignup")}</div>
              <div className="sk-faint" style={{ fontSize: 12, marginTop: 4 }}>
                {data.effective_signup_enabled ? t("storefront.effectiveOn") : t("storefront.effectiveOff")}
              </div>
            </div>
            <Toggle
              on={data.public_signup_enabled}
              onChange={(v) => save({ public_signup_enabled: v })}
              disabled={busy}
            />
          </div>
          <div className="sk-row" style={{ justifyContent: "space-between" }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{t("storefront.resellerApply")}</div>
              <div className="sk-faint" style={{ fontSize: 12, marginTop: 4 }}>
                {data.effective_reseller_apply_enabled ? t("storefront.effectiveOn") : t("storefront.effectiveOff")}
              </div>
            </div>
            <Toggle
              on={data.reseller_apply_enabled}
              onChange={(v) => save({ reseller_apply_enabled: v })}
              disabled={busy}
            />
          </div>
          <Field label={t("storefront.headline")}>
            <Input value={h} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setHeadline(e.target.value)} />
          </Field>
          <Field label={t("storefront.tagline")}>
            <Textarea value={tg} onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setTagline(e.target.value)} rows={2} />
          </Field>
          <Button variant="primary" disabled={busy} onClick={() => save({})}>
            {t("common.save")}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHead title={t("storefront.linksTitle")} />
        <div className="sk-stack" style={{ gap: 12 }}>
          <LinkRow label={t("storefront.linkLanding")} url={landingUrl} onCopy={() => copy(landingUrl)} />
          <LinkRow label={t("storefront.linkRegister")} url={registerUrl} onCopy={() => copy(registerUrl)} />
          <LinkRow label={t("storefront.linkBecome")} url={becomeUrl} onCopy={() => copy(becomeUrl)} />
          <div className="sk-row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <code style={{ fontSize: 13 }}>{data.invite_code}</code>
            <Button variant="ghost" className="sm" onClick={() => copy(data.invite_code)}>
              {t("storefront.copyInvite")}
            </Button>
            <Button variant="ghost" className="sm" disabled={busy} onClick={rotate}>
              {t("storefront.rotateInvite")}
            </Button>
            <a className="sk-btn sm ghost" href={landingUrl} target="_blank" rel="noreferrer">
              {t("storefront.preview")}
            </a>
          </div>
        </div>
      </Card>

      <Card>
        <CardHead title={t("storefront.applicationsTitle")} />
        {apps.loading ? (
          <SkeletonRows rows={3} cols={2} />
        ) : !(apps.data || []).length ? (
          <EmptyState title={t("storefront.noApplications")} />
        ) : (
          <div className="sk-stack" style={{ gap: 10 }}>
            {(apps.data || []).map((row) => (
              <div
                key={row.id}
                className="sk-row"
                style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}
              >
                <div>
                  <div style={{ fontWeight: 600 }}>{row.username}</div>
                  <div className="sk-faint" style={{ fontSize: 12 }}>
                    {[row.display_name, row.contact].filter(Boolean).join(" · ")}
                  </div>
                  {row.message ? (
                    <div className="sk-faint" style={{ fontSize: 12, marginTop: 4 }}>{row.message}</div>
                  ) : null}
                </div>
                <div className="sk-row" style={{ gap: 8 }}>
                  <Button variant="primary" className="sm" onClick={() => approve(row.id)}>
                    {t("storefront.approve")}
                  </Button>
                  <Button variant="ghost" className="sm" onClick={() => reject(row.id)}>
                    {t("storefront.reject")}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

const LinkRow: FC<{ label: string; url: string; onCopy: () => void }> = ({ label, url, onCopy }) => {
  const { t } = useTranslation();
  return (
    <div>
      <div className="sk-faint" style={{ fontSize: 12, marginBottom: 4 }}>{label}</div>
      <div className="sk-row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <code style={{ fontSize: 12, wordBreak: "break-all" }}>{url}</code>
        <Button variant="ghost" className="sm" onClick={onCopy}>{t("common.copy", { defaultValue: "Copy" })}</Button>
      </div>
    </div>
  );
};
