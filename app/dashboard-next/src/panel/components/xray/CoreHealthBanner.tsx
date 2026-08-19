import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { Callout } from "../ui";

interface CoreStats {
  version: string;
  started: boolean;
  startup_error?: string | null;
  failed_inbound_tag?: string | null;
  failed_port?: number | null;
}

export const CoreHealthBanner: FC<{ highlightTag?: string | null }> = ({ highlightTag }) => {
  const { t } = useTranslation();
  const [stats, setStats] = useState<CoreStats | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      api.get<CoreStats>("/core")
        .then((d) => alive && setStats(d))
        .catch(() => alive && setStats(null));
    };
    load();
    const id = window.setInterval(load, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (!stats || stats.started) return null;

  const tag = stats.failed_inbound_tag || highlightTag;
  const title = tag
    ? t("inbounds.coreDownInbound", { tag })
    : t("inbounds.coreDownTitle");

  return (
    <Callout tone="danger" title={title}>
      {stats.startup_error || t("inbounds.coreDownBody")}
      {stats.failed_port ? (
        <div className="sk-faint" style={{ marginTop: 6, fontSize: 12 }}>
          {t("inbounds.coreDownPort", { port: stats.failed_port })}
        </div>
      ) : null}
    </Callout>
  );
};
