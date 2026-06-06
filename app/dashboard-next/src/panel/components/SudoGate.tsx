import { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { PageHeader } from "./Shell";
import { Callout } from "./ui";

/** Wraps sudo-only pages with a consistent header and access gate. */
export const SudoGate: FC<{
  titleKey: string;
  subtitleKey?: string;
  descKey?: string;
  children: ReactNode;
}> = ({ titleKey, subtitleKey, descKey, children }) => {
  const { t } = useTranslation();
  const { admin } = useApp();

  return (
    <div>
      <PageHeader
        title={t(titleKey)}
        subtitle={subtitleKey ? t(subtitleKey) : undefined}
        description={descKey ? t(descKey) : undefined}
      />
      {!admin?.is_sudo ? <Callout tone="warn">{t("common.sudoOnly")}</Callout> : children}
    </div>
  );
};
