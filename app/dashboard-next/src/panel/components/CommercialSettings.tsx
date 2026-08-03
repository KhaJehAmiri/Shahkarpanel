import { FC, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useFetch } from "../lib/useFetch";
import {
  Button, Callout, Card, CardHead, EmptyState, Field, Input, SkeletonRows, Toggle, useToast,
} from "./ui";

export interface PlatformSetting {
  key: string;
  value: string | number | boolean | null | number[] | Record<string, unknown>[];
  type: string;
  has_secret: boolean;
  is_set: boolean;
}

const SECTIONS: { id: string; keys: string[] }[] = [
  {
    id: "billing",
    keys: [
      "billing.currency_label",
      "billing.usage_rate_per_gb",
      "billing.default_package_price",
      "billing.default_package_bytes",
      "billing.wallet_low_threshold",
      "billing.job_interval_seconds",
    ],
  },
  {
    id: "payment",
    keys: [
      "payment.gateway_enabled",
      "payment.card_enabled",
      "payment.demo_enabled",
      "payment.min_amount",
      "payment.max_amount",
      "payment.stripe_enabled",
      "payment.stripe_publishable_key",
      "payment.stripe_secret_key",
      "payment.stripe_webhook_secret",
      "payment.centralpay_enabled",
      "payment.centralpay_api_key",
      "payment.centralpay_merchant_id",
      "payment.centralpay_relay_base",
      "payment.centralpay_relay_secret",
      "payment.centralpay_http_proxy",
    ],
  },
  {
    id: "reseller",
    keys: [
      "reseller.sub_reseller_max",
      "reseller.default_commission_percent",
    ],
  },
  {
    id: "portal",
    keys: [
      "portal.max_child_accounts",
    ],
  },
  {
    id: "storefront",
    keys: [
      "storefront.enabled",
      "storefront.public_signup_enabled",
      "storefront.reseller_apply_enabled",
    ],
  },
];

export const CommercialSettings: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const { data, loading, error, status, reload } = useFetch<PlatformSetting[]>(
    () => api.get("/platform-settings"),
    [],
  );
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const byKey = useMemo(() => {
    const m: Record<string, PlatformSetting> = {};
    (data || []).forEach((s) => { m[s.key] = s; });
    return m;
  }, [data]);

  if (status === 403) return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;
  if (loading) return <Card><SkeletonRows rows={8} cols={2} /></Card>;
  if (error) return <EmptyState title={t("common.error")} desc={error} />;

  const displayValue = (s: PlatformSetting): string => {
    if (draft[s.key] !== undefined) return draft[s.key];
    if (s.type === "bool") return s.value ? "true" : "false";
    if (s.value === null || s.value === undefined) return "";
    return String(s.value);
  };

  const setField = (key: string, value: string) => {
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const save = async () => {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const [key, raw] of Object.entries(draft)) {
        const spec = byKey[key];
        if (!spec) continue;
        if (spec.type === "bool") {
          payload[key] = raw === "true";
        } else if (spec.type === "int") {
          payload[key] = parseInt(raw, 10) || 0;
        } else {
          payload[key] = raw;
        }
      }
      await api.put("/platform-settings", { settings: payload });
      toast.push(t("common.saved"), "success");
      setDraft({});
      reload();
    } catch (e: any) {
      toast.push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const hasChanges = Object.keys(draft).length > 0;

  return (
    <div className="sk-stack" style={{ gap: 20 }}>
      <Callout tone="info">{t("commercial.hint")}</Callout>
      <Callout tone="info">
        {t("commercial.resellerTariffsHint", {
          defaultValue:
            "Reseller wholesale tariffs (volume or unlimited) are managed under Resellers → Tariffs — not here and not under Billing → Plans.",
        })}
      </Callout>
      {SECTIONS.map((section) => (
        <Card key={section.id}>
          <CardHead title={t(`commercial.section.${section.id}`)} />
          <div className="sk-stack" style={{ gap: 14 }}>
            {section.keys.map((key) => {
              const s = byKey[key];
              if (!s) return null;
              const label = t(`commercial.keys.${key}`, { defaultValue: key });
              const hint = t(`commercial.hints.${key}`, { defaultValue: "" });

              if (s.type === "bool") {
                const on = displayValue(s) === "true";
                return (
                  <div key={key} className="sk-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{label}</div>
                      {hint && <div className="sk-faint" style={{ fontSize: 12, marginTop: 4 }}>{hint}</div>}
                    </div>
                    <Toggle
                      on={on}
                      onChange={() => setField(key, on ? "false" : "true")}
                    />
                  </div>
                );
              }

              return (
                <Field key={key} label={label} hint={hint || undefined}>
                  <Input
                    type={s.type === "int" ? "number" : s.has_secret ? "password" : "text"}
                    value={displayValue(s)}
                    placeholder={s.has_secret && s.is_set ? "••••••••" : ""}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setField(key, e.target.value)}
                  />
                </Field>
              );
            })}
            {section.id === "payment" && (
              <>
                <Callout tone="info">
                  {t("commercial.cardMultiManageHint", {
                    defaultValue:
                      "Add multiple card-to-card numbers under Billing → My card-to-card. Customers and resellers see a random card by default and can swipe between cards.",
                  })}
                </Callout>
                <Callout tone="info">
                  {t("commercial.stripeWebhookUrl", { url: `${window.location.origin}/api/billing/webhook/stripe` })}
                </Callout>
                <Callout tone="warn">
                  {t("commercial.stripeWebhookRequired", {
                    defaultValue:
                      "Stripe stays disabled until webhook secret is set. Unsigned webhooks are rejected.",
                  })}
                </Callout>
              </>
            )}
          </div>
        </Card>
      ))}
      <div className="sk-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={busy || !hasChanges} onClick={save}>{t("common.save")}</Button>
      </div>
    </div>
  );
};
