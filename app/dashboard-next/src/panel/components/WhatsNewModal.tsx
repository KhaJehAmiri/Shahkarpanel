import { FC } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal } from "./ui";

export const WhatsNewModal: FC<{
  version: string;
  notes: string[];
  onClose: () => void;
}> = ({ version, notes, onClose }) => {
  const { t } = useTranslation();

  return (
    <Modal
      open
      onClose={onClose}
      title=""
      hideHead
      wide
      footer={<Button variant="primary" onClick={onClose}>{t("system.whatsNewGotIt")}</Button>}
    >
      <div className="nx-whatsnew-modal">
        <div className="nx-whatsnew-hero">
          <div className="nx-whatsnew-badge">N</div>
          <div>
            <div className="nx-whatsnew-kicker">{t("system.whatsNewKicker")}</div>
            <h2 className="nx-whatsnew-title">{t("system.whatsNewTitle", { version })}</h2>
          </div>
        </div>
        {notes.length > 0 ? (
          <ul className="nx-whatsnew-notes">
            {notes.map((line) => (
              <li key={line}>
                <span className="nx-whatsnew-dot" aria-hidden />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="nx-muted">{t("system.whatsNewEmpty")}</p>
        )}
      </div>
    </Modal>
  );
};
