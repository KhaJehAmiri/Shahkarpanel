import {
  createContext, FC, InputHTMLAttributes, ReactNode, useCallback, useContext, useState,
} from "react";
import { useTranslation } from "react-i18next";
import { copyToClipboard } from "../lib/clipboard";
import { IcCheck, IcClose } from "./icons";

/* ------------------------------- Button -------------------------------- */
export const Button: FC<{
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "danger" | "ghost";
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  title?: string;
}> = ({ children, onClick, variant = "default", size = "md", disabled, type = "button", className = "", title }) => (
  <button
    type={type}
    title={title}
    disabled={disabled}
    onClick={onClick}
    className={`nx-btn ${variant} ${size === "sm" ? "sm" : ""} ${className}`}
  >
    {children}
  </button>
);

/* -------------------------------- Card --------------------------------- */
export const Card: FC<{ children: ReactNode; className?: string; pad0?: boolean; style?: React.CSSProperties }> = ({ children, className = "", pad0, style }) => (
  <div className={`nx-card ${pad0 ? "pad0" : ""} ${className}`} style={style}>{children}</div>
);

export const CardHead: FC<{ title: string; desc?: string; actions?: ReactNode }> = ({ title, desc, actions }) => (
  <div className="nx-card-head">
    <div>
      <div className="nx-card-title">{title}</div>
      {desc && <div className="nx-card-desc">{desc}</div>}
    </div>
    {actions && <div className="nx-row">{actions}</div>}
  </div>
);

/* -------------------------------- Stat --------------------------------- */
export const Stat: FC<{ label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode }> = ({ label, value, sub, icon }) => (
  <div className="nx-stat">
    <div className="nx-stat-label">{icon}{label}</div>
    <div className="nx-stat-value">{value}</div>
    {sub && <div className="nx-stat-sub">{sub}</div>}
  </div>
);

/* -------------------------------- Pill --------------------------------- */
export const Pill: FC<{ children: ReactNode; tone?: "ok" | "danger" | "warn" | "info" | "accent" | "default"; dot?: boolean }> = ({ children, tone = "default", dot }) => (
  <span className={`nx-pill ${tone}`}>{dot && <span className="nx-dot" />}{children}</span>
);

/* ------------------------------- Toggle -------------------------------- */
export const Toggle: FC<{ on: boolean; onChange: (v: boolean) => void; disabled?: boolean }> = ({ on, onChange, disabled }) => (
  <button
    type="button"
    disabled={disabled}
    className={`nx-toggle ${on ? "on" : ""}`}
    onClick={() => !disabled && onChange(!on)}
    style={disabled ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
  >
    <span className="nx-toggle-knob" />
  </button>
);

/* ------------------------------- Inputs -------------------------------- */
export const Field: FC<{ label?: string; hint?: string; children: ReactNode }> = ({ label, hint, children }) => (
  <div className="nx-field">
    {label && <label className="nx-label">{label}</label>}
    {children}
    {hint && <span className="nx-hint">{hint}</span>}
  </div>
);

export const Input: FC<InputHTMLAttributes<HTMLInputElement>> = (props) => (
  <input className="nx-input" {...props} />
);
export const Textarea: FC<any> = (props) => <textarea className="nx-textarea" {...props} />;
export const Select: FC<any> = ({ children, ...rest }) => (
  <select className="nx-select" {...rest}>{children}</select>
);

/* -------------------------------- Tabs --------------------------------- */
export const Tabs: FC<{ tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void }> = ({ tabs, active, onChange }) => (
  <div className="nx-tabs">
    {tabs.map((t) => (
      <button key={t.id} className={`nx-tab ${active === t.id ? "active" : ""}`} onClick={() => onChange(t.id)}>
        {t.label}
      </button>
    ))}
  </div>
);

/* ------------------------------- Callout ------------------------------- */
export const Callout: FC<{ tone?: "info" | "warn" | "danger" | "ok"; title?: string; children: ReactNode }> = ({ tone = "info", title, children }) => (
  <div className={`nx-callout ${tone}`}>
    <div>
      {title && <div className="nx-callout-title">{title}</div>}
      <div>{children}</div>
    </div>
  </div>
);

/* ------------------------------ EmptyState ----------------------------- */
export const EmptyState: FC<{ title: string; desc?: string; steps?: string[]; action?: ReactNode }> = ({ title, desc, steps, action }) => (
  <div className="nx-empty">
    <div className="nx-empty-icon" aria-hidden>·</div>
    <div className="nx-empty-title">{title}</div>
    {desc && <div className="nx-empty-desc">{desc}</div>}
    {steps && steps.length > 0 && (
      <ol className="nx-empty-steps">
        {steps.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
    )}
    {action && <div className="nx-empty-action">{action}</div>}
  </div>
);

/* -------------------------------- Modal -------------------------------- */
export const Modal: FC<{
  open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}> = ({ open, title, onClose, children, footer, wide }) => {
  if (!open) return null;
  return (
    <div className="nx-overlay" onClick={onClose}>
      <div className={`nx-modal${wide ? " wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="nx-modal-head">
          <div className="nx-card-title">{title}</div>
          <button className="nx-btn icon ghost" onClick={onClose}><IcClose /></button>
        </div>
        <div className="nx-modal-body">{children}</div>
        {footer && <div className="nx-modal-foot">{footer}</div>}
      </div>
    </div>
  );
};

/* ------------------------------- Drawer -------------------------------- */
export const Drawer: FC<{ open: boolean; title: ReactNode; onClose: () => void; children: ReactNode }> = ({ open, title, onClose, children }) => {
  if (!open) return null;
  return (
    <>
      <div className="nx-drawer-overlay" onClick={onClose} />
      <div className="nx-drawer">
        <div className="nx-drawer-head">
          <div className="nx-card-title">{title}</div>
          <button className="nx-btn icon ghost" onClick={onClose}><IcClose /></button>
        </div>
        <div className="nx-drawer-body">{children}</div>
      </div>
    </>
  );
};

/* ------------------------------ SectionHelp ----------------------------- */
export const SectionHelp: FC<{ title: ReactNode; children: ReactNode; tone?: "info" | "warn" | "ok" }> = ({ title, children, tone = "info" }) => (
  <div className={`nx-help ${tone}`}>
    <div className="nx-help-mark" aria-hidden>?</div>
    <div className="nx-help-body">
      <div className="nx-help-title">{title}</div>
      <div className="nx-help-text">{children}</div>
    </div>
  </div>
);

/* ------------------------------- HelpTip -------------------------------- */
export const HelpTip: FC<{ text: ReactNode; placement?: "top" | "bottom" }> = ({ text, placement = "top" }) => {
  const { t } = useTranslation();
  return (
    <span className={`nx-tip nx-tip-${placement}`} tabIndex={0} aria-label={t("common.help")}>
      <span className="nx-tip-mark" aria-hidden>?</span>
      <span className="nx-tip-bubble" role="tooltip">{text}</span>
    </span>
  );
};

/* ----------------------------- Checkbox -------------------------------- */
export const Checkbox: FC<{ checked: boolean; onChange?: () => void }> = ({ checked, onChange }) => (
  <span className={`nx-checkbox ${checked ? "on" : ""}`} onClick={onChange}>
    <IcCheck size={13} />
  </span>
);

/* ------------------------------ CopyField ------------------------------ */
export const CopyField: FC<{ value: string; label?: string; mono?: boolean; multiline?: boolean }> = ({ value, label, mono = true, multiline }) => {
  const { push } = useToast();
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopied(true);
      push(t("common.copiedToClipboard"), "success");
      window.setTimeout(() => setCopied(false), 1400);
    } else {
      push(t("common.copyFailedHint"), "error");
    }
  };
  return (
    <div className="nx-copy-field">
      {label && <label className="nx-label">{label}</label>}
      <div className="nx-copy-row">
        {multiline ? (
          <textarea className={`nx-input ${mono ? "nx-mono" : ""}`} readOnly value={value} rows={3} onFocus={(e) => e.target.select()} />
        ) : (
          <input className={`nx-input ${mono ? "nx-mono" : ""}`} readOnly value={value} onFocus={(e) => e.target.select()} />
        )}
        <button type="button" className={`nx-copy-btn ${copied ? "ok" : ""}`} onClick={copy} aria-label={t("common.copy")}>
          {copied ? <IcCheck size={14} /> : <span aria-hidden style={{ fontSize: 14 }}>⧉</span>}
          <span className="nx-copy-btn-label">{copied ? t("common.copied") : t("common.copy")}</span>
        </button>
      </div>
    </div>
  );
};

export const CopyButton: FC<{ value: string; size?: "sm" | "md"; label?: string; className?: string }> = ({ value, size = "sm", label, className = "" }) => {
  const { push } = useToast();
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopied(true);
      push(t("common.copied"), "success");
      window.setTimeout(() => setCopied(false), 1400);
    } else push(t("common.copyFailed"), "error");
  };
  const copyLabel = label || t("common.copy");
  return (
    <button type="button" onClick={copy} className={`nx-btn ${size === "sm" ? "sm" : ""} ${className}`} aria-label={copyLabel} title={copyLabel}>
      {copied ? <IcCheck size={14} /> : <span aria-hidden style={{ fontSize: 14 }}>⧉</span>}
      {label ? <span>{copied ? t("common.copied") : label}</span> : null}
    </button>
  );
};

/* ------------------------------ UsageBar ------------------------------- */
export const UsageBar: FC<{ pct: number }> = ({ pct }) => {
  const v = Math.max(0, Math.min(100, pct));
  const tone = v >= 90 ? "danger" : v >= 70 ? "warn" : "";
  return (
    <div className="nx-bar" title={`${v.toFixed(0)}%`}>
      <div className={`nx-bar-fill ${tone}`} style={{ width: `${v}%` }} />
    </div>
  );
};

/* ------------------------------ Loading -------------------------------- */
export const Loading: FC<{ label?: string }> = ({ label }) => (
  <div className="nx-loading">{label || "Loading…"}</div>
);

export const SkeletonRows: FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 4 }) => (
  <div className="nx-stack">
    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} className="nx-row" style={{ gap: 16 }}>
        {Array.from({ length: cols }).map((__, j) => (
          <div key={j} className="nx-skel" style={{ height: 16, flex: j === 0 ? 2 : 1 }} />
        ))}
      </div>
    ))}
  </div>
);

/* -------------------------------- Toasts ------------------------------- */
type Toast = { id: number; msg: string; kind: "info" | "success" | "error" };
const ToastCtx = createContext<{ push: (msg: string, kind?: Toast["kind"]) => void }>({ push: () => {} });
export const useToast = () => useContext(ToastCtx);

const TOAST_ICON: Record<Toast["kind"], string> = { success: "✓", error: "!", info: "i" };

export const ToastProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const { t: tr } = useTranslation();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback((msg: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, msg, kind }]);
    window.setTimeout(() => dismiss(id), 3800);
  }, [dismiss]);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="nx-toasts" role="region" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`nx-toast ${t.kind}`} role="status">
            <span className="nx-toast-icon" aria-hidden>{TOAST_ICON[t.kind]}</span>
            <span className="nx-toast-msg">{t.msg}</span>
            <button className="nx-toast-x" onClick={() => dismiss(t.id)} aria-label={tr("common.dismiss")}>×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
};
