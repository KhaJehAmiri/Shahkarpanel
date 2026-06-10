import { ChangeEvent, FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Callout, Card } from "../ui";

export const JsonSection: FC<{
  config: Record<string, unknown>;
  onSave: (parsed: Record<string, unknown>) => void;
  saving: boolean;
}> = ({ config, onSave, saving }) => {
  const { t } = useTranslation();
  const [text, setText] = useState(() => JSON.stringify(config, null, 2));
  const [err, setErr] = useState<string | null>(null);

  const apply = () => {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      setErr(null);
      onSave(parsed);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : t("automation.invalidJson"));
    }
  };

  const syncFromConfig = () => {
    setText(JSON.stringify(config, null, 2));
    setErr(null);
  };

  return (
    <div className="nx-stack">
      <Callout tone="warn" title={t("xray.jsonTitle")}>{t("xray.jsonDesc")}</Callout>
      <Card>
        <textarea
          className="nx-code-editor"
          rows={22}
          value={text}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setText(e.target.value)}
          dir="ltr"
          spellCheck={false}
        />
        {err && <div style={{ color: "var(--nx-danger)", fontSize: 12, marginTop: 8 }}>{err}</div>}
      </Card>
      <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <Button variant="ghost" onClick={syncFromConfig}>{t("common.retry")}</Button>
        <Button variant="primary" disabled={saving} onClick={apply}>{t("common.save")}</Button>
      </div>
    </div>
  );
};
