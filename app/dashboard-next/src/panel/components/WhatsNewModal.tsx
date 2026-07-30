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
      <div className="sk-whatsnew-modal">
        <div className="sk-whatsnew-hero">
          <div className="sk-whatsnew-badge">N</div>
          <div>
            <div className="sk-whatsnew-kicker">{t("system.whatsNewKicker")}</div>
            <h2 className="sk-whatsnew-title">{t("system.whatsNewTitle", { version })}</h2>
          </div>
        </div>
        {notes.length > 0 ? (
          <ul className="sk-whatsnew-notes">
            {notes.map((line) => (
              <li key={line}>
                <span className="sk-whatsnew-dot" aria-hidden />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sk-muted">{t("system.whatsNewEmpty")}</p>
        )}
      </div>
    </Modal>
  );
};
