import { ChangeEvent, FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import { Button, Callout, Field, Input, Modal, Pill, useToast } from "../ui";

type WarpAccount = {
  registered: boolean;
  device_id?: string;
  license_key?: string;
  account_type?: string;
  premium_data?: number;
  quota?: number;
  outbound?: Record<string, unknown>;
};

export const WarpDialog: FC<{
  outbounds: Record<string, unknown>[];
  onClose: () => void;
  /** Add (or replace) the warp outbound and persist the whole config. */
  onAddOutbound: (outbound: Record<string, unknown>) => void;
}> = ({ outbounds, onClose, onAddOutbound }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [account, setAccount] = useState<WarpAccount | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [license, setLicense] = useState("");

  const warpTag = (account?.outbound?.tag as string) || "warp";
  const alreadyAdded = outbounds.some((o) => String(o.tag) === warpTag);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.get<WarpAccount>("/core/warp");
      setAccount(data);
      setLicense(data.license_key || "");
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : "Failed to load WARP", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const register = async () => {
    setBusy(true);
    try {
      const data = await api.post<WarpAccount>("/core/warp/register", {});
      setAccount(data);
      setLicense(data.license_key || "");
      toast.push(t("warp.registered"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("warp.registerFailed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const applyLicense = async () => {
    if (!license.trim()) return;
    setBusy(true);
    try {
      const data = await api.post<WarpAccount>("/core/warp/license", { license: license.trim() });
      setAccount(data);
      toast.push(t("warp.licenseApplied"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : t("warp.licenseFailed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm(t("warp.confirmDelete"))) return;
    setBusy(true);
    try {
      await api.del("/core/warp");
      setAccount({ registered: false });
      setLicense("");
      toast.push(t("warp.deleted"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof ApiError ? e.message : "Failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const addToConfig = () => {
    if (!account?.outbound) return;
    onAddOutbound(account.outbound);
  };

  const isPlus = (account?.account_type && account.account_type !== "free") || (account?.premium_data ?? 0) > 0;

  return (
    <Modal
      open
      title={t("warp.title")}
      onClose={onClose}
      footer={<Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>}
    >
      <div className="nx-stack" style={{ gap: 16 }}>
        <Callout tone="info" title={t("warp.aboutTitle")}>{t("warp.about")}</Callout>

        {loading ? (
          <div style={{ color: "var(--nx-muted)" }}>{t("common.loading")}</div>
        ) : account?.registered ? (
          <>
            <div className="nx-row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Pill tone="ok" dot>{t("warp.statusActive")}</Pill>
              <Pill tone={isPlus ? "accent" : "default"}>{isPlus ? "WARP+" : "WARP free"}</Pill>
            </div>
            <Field label={t("warp.deviceId")}>
              <Input value={account.device_id || ""} readOnly className="nx-mono" />
            </Field>
            <Field label={t("warp.license")} hint={t("warp.licenseHint")}>
              <div className="nx-row" style={{ gap: 8 }}>
                <Input
                  value={license}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setLicense(e.target.value)}
                  placeholder="xxxxxxxx-xxxx-xxxx"
                  className="nx-mono"
                />
                <Button onClick={applyLicense} disabled={busy || !license.trim()}>{t("warp.applyLicense")}</Button>
              </div>
            </Field>

            {alreadyAdded ? (
              <Callout tone="ok">{t("warp.outboundPresent", { tag: warpTag })}</Callout>
            ) : (
              <Callout tone="warn">{t("warp.outboundMissing")}</Callout>
            )}

            <div className="nx-row" style={{ gap: 8, flexWrap: "wrap", justifyContent: "space-between" }}>
              <Button variant="danger" onClick={remove} disabled={busy}>{t("warp.delete")}</Button>
              <Button variant="primary" onClick={addToConfig} disabled={busy}>
                {alreadyAdded ? t("warp.updateOutbound") : t("warp.addOutbound")}
              </Button>
            </div>
          </>
        ) : (
          <>
            <Callout tone="warn">{t("warp.notRegistered")}</Callout>
            <Button variant="primary" onClick={register} disabled={busy}>
              {busy ? t("warp.registering") : t("warp.register")}
            </Button>
          </>
        )}
      </div>
    </Modal>
  );
};
