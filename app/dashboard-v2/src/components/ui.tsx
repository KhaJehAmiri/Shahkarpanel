import {
  createContext, FC, ReactNode, useCallback, useContext, useState,
} from "react";
import { IcClose } from "./icons";

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
export const Card: FC<{ children: ReactNode; className?: string; pad0?: boolean }> = ({ children, className = "", pad0 }) => (
  <div className={`nx-card ${pad0 ? "pad0" : ""} ${className}`}>{children}</div>
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

export const Input: FC<any> = (props) => <input className="nx-input" {...props} />;
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
export const EmptyState: FC<{ title: string; desc?: string; action?: ReactNode }> = ({ title, desc, action }) => (
  <div className="nx-empty">
    <div className="nx-empty-title">{title}</div>
    {desc && <div className="nx-empty-desc">{desc}</div>}
    {action}
  </div>
);

/* -------------------------------- Modal -------------------------------- */
export const Modal: FC<{ open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }> = ({ open, title, onClose, children, footer }) => {
  if (!open) return null;
  return (
    <div className="nx-overlay" onClick={onClose}>
      <div className="nx-modal" onClick={(e) => e.stopPropagation()}>
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

export const ToastProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((msg: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="nx-toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`nx-toast ${t.kind}`}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
};
