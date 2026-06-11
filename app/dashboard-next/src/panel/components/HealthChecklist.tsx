import { FC } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { IcCheck } from "./icons";

export type HealthItem = {
  id: string;
  ok: boolean;
  label: string;
  hint?: string;
  to: string;
  /** Optional steps are shown as guidance but do not block setup completion. */
  optional?: boolean;
};

const RING_R = 30;
const RING_C = 2 * Math.PI * RING_R;

export const HealthChecklist: FC<{ items: HealthItem[] }> = ({ items }) => {
  const { t } = useTranslation();
  const required = items.filter((i) => !i.optional);
  const done = required.filter((i) => i.ok).length;
  const pct = required.length ? Math.round((done / required.length) * 100) : 100;
  const allDone = required.length > 0 && done === required.length;

  return (
    <div className="nx-glass-card nx-health">
      <div className="nx-health-head">
        <div className="nx-health-ring" role="img" aria-label={`${pct}%`}>
          <svg width="76" height="76" viewBox="0 0 76 76">
            <defs>
              <linearGradient id="nxHealthGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="var(--nx-accent)" />
                <stop offset="100%" stopColor="var(--nx-accent-2)" />
              </linearGradient>
            </defs>
            <circle cx="38" cy="38" r={RING_R} fill="none" stroke="var(--nx-surface-3)" strokeWidth="7" />
            <circle
              cx="38" cy="38" r={RING_R} fill="none"
              stroke="url(#nxHealthGrad)" strokeWidth="7" strokeLinecap="round"
              strokeDasharray={`${(pct / 100) * RING_C} ${RING_C}`}
              transform="rotate(-90 38 38)"
              className="nx-health-ring-arc"
            />
          </svg>
          <span className="nx-health-ring-pct">{pct}%</span>
        </div>
        <div className="nx-health-headings">
          <div className="nx-health-title">{t("overview.healthTitle")}</div>
          <div className="nx-health-sub">{t("overview.healthSub", { done, total: required.length })}</div>
        </div>
        {allDone && (
          <span className="nx-health-done-badge">
            <IcCheck /> {t("copilot.done")}
          </span>
        )}
      </div>

      <div className="nx-health-steps">
        {items.map((item, idx) => (
          <Link key={item.id} to={item.to} className={`nx-health-step ${item.ok ? "ok" : "todo"}${item.optional ? " optional" : ""}`}>
            <span className="nx-health-step-mark">
              {item.ok ? <IcCheck /> : <span className="nx-health-step-num">{idx + 1}</span>}
            </span>
            <span className="nx-health-step-body">
              <b>{item.label}{item.optional ? ` (${t("common.optional")})` : ""}</b>
              {item.hint ? <small>{item.hint}</small> : null}
            </span>
            <span className="nx-health-step-go" aria-hidden>→</span>
          </Link>
        ))}
      </div>
    </div>
  );
};
