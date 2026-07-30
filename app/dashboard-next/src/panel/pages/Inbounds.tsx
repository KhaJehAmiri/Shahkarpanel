import { FC, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { PageHeader } from "../components/Shell";
import { InboundsSection } from "../components/xray/InboundsSection";
import { useXrayConfig } from "../components/xray/useXrayConfig";
import { Button, Callout, Card, EmptyState, SkeletonRows, useToast } from "../components/ui";
import { IcRefresh } from "../components/icons";

export const Inbounds: FC<{ embedded?: boolean }> = ({ embedded }) => {
  const { t } = useTranslation();
  const { hasPermission } = useApp();
  const toast = useToast();
  const { config, setConfig, loading, error, saving, reload, save } = useXrayConfig();

  useEffect(() => {
    reload();
  }, [reload]);

  if (!hasPermission("core:read")) {
    return <Callout tone="warn">{t("common.sudoOnly")}</Callout>;
  }

  const canWrite = hasPermission("core:write");

  const persist = async (cfg?: Record<string, unknown>) => {
    const target = cfg ?? config;
    if (!target) return;
    try {
      await save(target);
      if (!cfg) toast.push(t("xray.savedRestart"), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
      throw e;
    }
  };

  return (
    <div>
      {!embedded && (
        <PageHeader
          title={t("inbounds.title")}
          subtitle={t("inbounds.subtitle")}
          description={t("inbounds.description")}
          actions={
            <Button variant="ghost" onClick={reload} disabled={saving || loading}>
              <IcRefresh className="sk-ico" /> {t("common.refresh")}
            </Button>
          }
        />
      )}

      {loading ? (
        <Card><SkeletonRows rows={6} cols={5} /></Card>
      ) : error ? (
        <EmptyState
          title={t("common.error")}
          desc={error}
          action={<Button onClick={reload}>{t("common.retry")}</Button>}
        />
      ) : config ? (
        <InboundsSection
          config={config}
          onChange={setConfig}
          onSave={persist}
          saving={saving}
          readOnly={!canWrite}
        />
      ) : null}
    </div>
  );
};
