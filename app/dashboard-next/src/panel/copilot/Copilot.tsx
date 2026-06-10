"use client";

import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../context/AppContext";
import { useCopilot } from "./CopilotContext";
import {
  CopilotRecipe, CopilotSnapshot, RECIPES, emptySnapshot, fetchSnapshot, recipeProgress,
} from "./recipes";

const IcSpark: FC = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M12 2l1.8 5.4L19 9l-5.2 1.6L12 16l-1.8-5.4L5 9l5.2-1.6L12 2z" fill="currentColor" />
    <circle cx="18.5" cy="17.5" r="1.6" fill="currentColor" opacity="0.8" />
  </svg>
);

export const Copilot: FC = () => {
  const { t } = useTranslation();
  const { admin, isEnabled } = useApp();
  const {
    open, setOpen, activeRecipe, setActiveRecipe, dismissed, dismiss, requestIntent,
  } = useCopilot();
  const [snap, setSnap] = useState<CopilotSnapshot>(emptySnapshot);

  const isSudo = !!admin?.is_sudo;

  const recipes = useMemo(
    () => RECIPES.filter((r) => (r.sudoOnly ? isSudo : true))
      .filter((r) => (r.requiresFlag ? isEnabled(r.requiresFlag) : true)),
    [isSudo, isEnabled],
  );

  // Poll the snapshot while the panel is open so checkmarks light up live.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const tick = () => fetchSnapshot(isSudo).then((s) => { if (alive) setSnap(s); }).catch(() => {});
    tick();
    const id = window.setInterval(tick, 4000);
    return () => { alive = false; window.clearInterval(id); };
  }, [open, isSudo]);

  if (!admin) return null;

  const recipe = recipes.find((r) => r.id === activeRecipe) || null;

  return (
    <>
      {open && (
        <>
          <div className="nx-copilot-scrim" onClick={() => setOpen(false)} />
          <aside className="nx-copilot" role="dialog" aria-label={t("copilot.title")}>
            <div className="nx-copilot-head">
              <div className="nx-row" style={{ gap: 10 }}>
                <span className="nx-copilot-avatar"><IcSpark /></span>
                <div>
                  <div className="nx-copilot-title">{t("copilot.title")}</div>
                  <div className="nx-copilot-sub">{t("copilot.greeting", { name: admin.username })}</div>
                </div>
              </div>
              <button className="nx-btn icon ghost" onClick={() => setOpen(false)} aria-label={t("common.cancel")}>✕</button>
            </div>

            <div className="nx-copilot-body">
              {recipe
                ? <RecipeView recipe={recipe} snap={snap} onBack={() => setActiveRecipe(null)} onAction={requestIntent} />
                : (
                  <>
                    <p className="nx-copilot-lead">{t("copilot.lead")}</p>
                    <div className="nx-copilot-list">
                      {recipes.map((r) => {
                        const p = recipeProgress(r, snap);
                        const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
                        const complete = p.total > 0 && p.done >= p.total;
                        return (
                          <button key={r.id} className="nx-copilot-card" onClick={() => setActiveRecipe(r.id)}>
                            <span className="nx-copilot-card-icon" aria-hidden>{r.icon}</span>
                            <span className="nx-copilot-card-main">
                              <span className="nx-copilot-card-title">
                                {t(r.titleKey)}
                                {complete && <span className="nx-copilot-badge ok">{t("copilot.done")}</span>}
                              </span>
                              <span className="nx-copilot-card-desc">{t(r.descKey)}</span>
                              {p.total > 0 && (
                                <span className="nx-copilot-progress" aria-hidden>
                                  <span className="nx-copilot-progress-fill" style={{ width: `${pct}%` }} />
                                </span>
                              )}
                            </span>
                            <span className="nx-copilot-card-chev" aria-hidden>›</span>
                          </button>
                        );
                      })}
                    </div>
                  </>
                )}
            </div>

            <div className="nx-copilot-foot">
              <button className="nx-btn ghost sm" onClick={dismiss}>{t("copilot.dismiss")}</button>
              <span className="nx-faint" style={{ fontSize: 11 }}>{t("copilot.footnote")}</span>
            </div>
          </aside>
        </>
      )}
    </>
  );
};

const RecipeView: FC<{
  recipe: CopilotRecipe;
  snap: CopilotSnapshot;
  onBack: () => void;
  onAction: (intent: any, hash?: string) => void;
}> = ({ recipe, snap, onBack, onAction }) => {
  const { t } = useTranslation();
  const p = recipeProgress(recipe, snap);
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;

  return (
    <div className="nx-copilot-recipe">
      <button className="nx-copilot-back" onClick={onBack}>‹ {t("copilot.back")}</button>
      <div className="nx-copilot-recipe-head">
        <span className="nx-copilot-card-icon" aria-hidden>{recipe.icon}</span>
        <div>
          <div className="nx-copilot-card-title">{t(recipe.titleKey)}</div>
          <div className="nx-copilot-card-desc">{t(recipe.descKey)}</div>
        </div>
      </div>
      {p.total > 0 && (
        <div className="nx-copilot-recipe-progress">
          <span className="nx-copilot-progress"><span className="nx-copilot-progress-fill" style={{ width: `${pct}%` }} /></span>
          <span className="nx-faint" style={{ fontSize: 11 }}>{t("copilot.stepsDone", { done: p.done, total: p.total })}</span>
        </div>
      )}

      <ol className="nx-copilot-steps">
        {recipe.steps.map((step, i) => {
          const done = step.check ? step.check(snap) : false;
          const auto = !!step.check;
          return (
            <li key={step.id} className={`nx-copilot-step ${done ? "done" : ""}`}>
              <span className="nx-copilot-step-num" aria-hidden>{done ? "✓" : i + 1}</span>
              <div className="nx-copilot-step-body">
                <div className="nx-copilot-step-title">{t(step.titleKey)}</div>
                <div className="nx-copilot-step-text">{t(step.bodyKey)}</div>
                {step.cta && !done && (
                  <button
                    className="nx-btn primary sm"
                    style={{ marginTop: 8 }}
                    onClick={() => onAction(step.cta!.intent ?? null, step.cta!.hash)}
                  >
                    {t(step.cta.labelKey)}
                  </button>
                )}
                {auto && !done && <span className="nx-copilot-step-hint">{t("copilot.autoDetect")}</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
