import { ChangeEvent, FC } from "react";
import { useTranslation } from "react-i18next";
import { LOG_LEVELS } from "../../lib/xrayHelpers";
import { Button, Callout, Card, Field, Select } from "../ui";

export const BasicsSection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
  onSave: () => void;
  saving: boolean;
}> = ({ config, onChange, onSave, saving }) => {
  const { t } = useTranslation();
  const log = (config.log || {}) as Record<string, unknown>;

  const setLog = (key: string, val: string) => {
    onChange({ ...config, log: { ...log, [key]: val } });
  };

  return (
    <div className="nx-stack">
      <Callout tone="info" title={t("xray.basicsTitle")}>{t("xray.basicsDesc")}</Callout>
      <Card>
        <Field label={t("xray.logLevel")}>
          <Select
            value={String(log.loglevel || "warning")}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setLog("loglevel", e.target.value)}
          >
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </Select>
        </Field>
        <Field label={`${t("xray.accessLog")} (${t("common.optional")})`}>
          <input
            className="nx-input"
            value={String(log.access || "")}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setLog("access", e.target.value)}
            placeholder="/var/log/xray/access.log"
          />
        </Field>
        <Field label={`${t("xray.errorLog")} (${t("common.optional")})`}>
          <input
            className="nx-input"
            value={String(log.error || "")}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setLog("error", e.target.value)}
            placeholder="/var/log/xray/error.log"
          />
        </Field>
      </Card>
      <div className="nx-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" disabled={saving} onClick={onSave}>{t("common.save")}</Button>
      </div>
    </div>
  );
};
