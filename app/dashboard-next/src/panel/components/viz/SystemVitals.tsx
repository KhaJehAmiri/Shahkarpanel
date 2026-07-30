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
  diskUsed?: number;
  diskTotal?: number;
}> = ({ cpu = 0, cpuCores = 0, memUsed = 0, memTotal = 1, diskUsed = 0, diskTotal = 0 }) => {
  const { t } = useTranslation();
  const memPct = memTotal > 0 ? (memUsed / memTotal) * 100 : 0;
  const diskPct = diskTotal > 0 ? (diskUsed / diskTotal) * 100 : 0;
  const cpuHist = useMetricHistory(cpu);
  const memHist = useMetricHistory(memPct);

  const cpuTone = cpu > 85 ? "danger" : cpu > 65 ? "warn" : "accent";
  const memTone = memPct > 90 ? "danger" : memPct > 75 ? "warn" : "info";
  const diskTone = diskPct > 90 ? "danger" : diskPct > 75 ? "warn" : "ok";

  return (
    <div className="sk-vitals-panel">
      <div className="sk-vital-cell">
        <div className="sk-vital-head">
          <span className="sk-vital-title">{t("overview.cpu")}</span>
          <span className="sk-vital-badge">{t("overview.cores", { n: cpuCores })}</span>
        </div>
        <div className="sk-vital-body">
          <GaugeRing value={cpu} label={t("overview.cpuLoad")} tone={cpuTone} size={100} />
          <div className="sk-vital-spark">
            <Sparkline data={cpuHist.length ? cpuHist : [cpu]} height={48} color="var(--sk-accent)" />
            <span className="sk-vital-spark-label">{t("overview.liveHistory")}</span>
          </div>
        </div>
      </div>

      <div className="sk-vital-cell">
        <div className="sk-vital-head">
          <span className="sk-vital-title">{t("overview.memory")}</span>
          <span className="sk-vital-badge">
            {formatBytes(memUsed)} / {formatBytes(memTotal)}
          </span>
        </div>
        <div className="sk-vital-body">
          <GaugeRing
            value={memPct}
            label={t("overview.ramUsed")}
            sub={formatBytes(memUsed)}
            tone={memTone}
            size={100}
          />
          <div className="sk-vital-spark">
            <Sparkline data={memHist.length ? memHist : [memPct]} height={48} color="var(--sk-info)" />
            <span className="sk-vital-spark-label">{t("overview.liveHistory")}</span>
          </div>
        </div>
      </div>

      {diskTotal > 0 && (
        <div className="sk-vital-cell">
          <div className="sk-vital-head">
            <span className="sk-vital-title">{t("overview.storage")}</span>
            <span className="sk-vital-badge">
              {formatBytes(diskUsed)} / {formatBytes(diskTotal)}
            </span>
          </div>
          <div className="sk-vital-body">
            <GaugeRing
              value={diskPct}
              label={t("overview.diskUsed")}
              sub={formatBytes(diskUsed)}
              tone={diskTone}
              size={100}
            />
            <div className="sk-vital-spark sk-vital-meta">
              <div className="sk-vital-meta-row">
                <span className="sk-vital-meta-label">{t("overview.diskUsedLabel")}</span>
                <span className="sk-vital-meta-value">{formatBytes(diskUsed)}</span>
              </div>
              <div className="sk-vital-meta-row">
                <span className="sk-vital-meta-label">{t("overview.diskFree")}</span>
                <span className="sk-vital-meta-value">{formatBytes(Math.max(0, diskTotal - diskUsed))}</span>
              </div>
              <div className="sk-vital-meta-row">
                <span className="sk-vital-meta-label">{t("overview.diskTotal")}</span>
                <span className="sk-vital-meta-value">{formatBytes(diskTotal)}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
