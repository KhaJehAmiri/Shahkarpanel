import { FC } from "react";
import { useTranslation } from "react-i18next";
import { formatBytes } from "../../lib/format";
import { useMetricHistory } from "../../lib/useMetricHistory";
import { GaugeRing } from "./GaugeRing";
import { Sparkline } from "../charts";

export const SystemVitals: FC<{
  cpu?: number;
  cpuCores?: number;
  memUsed?: number;
  memTotal?: number;
}> = ({ cpu = 0, cpuCores = 0, memUsed = 0, memTotal = 1 }) => {
  const { t } = useTranslation();
  const memPct = memTotal > 0 ? (memUsed / memTotal) * 100 : 0;
  const cpuHist = useMetricHistory(cpu);
  const memHist = useMetricHistory(memPct);

  const cpuTone = cpu > 85 ? "danger" : cpu > 65 ? "warn" : "accent";
  const memTone = memPct > 90 ? "danger" : memPct > 75 ? "warn" : "info";

  return (
    <div className="nx-vitals-grid">
      <div className="nx-glass-card nx-vital-card">
        <div className="nx-vital-head">
          <span className="nx-vital-title">{t("overview.cpu")}</span>
          <span className="nx-vital-badge">{t("overview.cores", { n: cpuCores })}</span>
        </div>
        <div className="nx-vital-body">
          <GaugeRing value={cpu} label={t("overview.cpuLoad")} tone={cpuTone} size={108} />
          <div className="nx-vital-spark">
            <Sparkline data={cpuHist.length ? cpuHist : [cpu]} height={56} color="var(--nx-accent)" />
            <span className="nx-vital-spark-label">{t("overview.liveHistory")}</span>
          </div>
        </div>
      </div>

      <div className="nx-glass-card nx-vital-card">
        <div className="nx-vital-head">
          <span className="nx-vital-title">{t("overview.memory")}</span>
          <span className="nx-vital-badge">
            {formatBytes(memUsed)} / {formatBytes(memTotal)}
          </span>
        </div>
        <div className="nx-vital-body">
          <GaugeRing
            value={memPct}
            label={t("overview.ramUsed")}
            sub={formatBytes(memUsed)}
            tone={memTone}
            size={108}
          />
          <div className="nx-vital-spark">
            <Sparkline data={memHist.length ? memHist : [memPct]} height={56} color="var(--nx-info)" />
            <span className="nx-vital-spark-label">{t("overview.liveHistory")}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
