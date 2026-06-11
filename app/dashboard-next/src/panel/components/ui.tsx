import {
  createContext, FC, InputHTMLAttributes, ReactNode, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import { createPortal } from "react-dom";
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
  <div className={`nx-card ${pad0 ? "pad0 nx-card-table" : "nx-glass-card"} ${className}`} style={style}>{children}</div>
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
export const Toggle: FC<{ on: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }> = ({ on, onChange, disabled, label }) => (
  <button
    type="button"
    role="switch"
    aria-checked={on}
    aria-label={label}
    title={label}
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

export const Input: FC<InputHTMLAttributes<HTMLInputElement>> = ({ className = "", ...props }) => (
  <input className={`nx-input ${className}`.trim()} {...props} />
);
export const Textarea: FC<any> = ({ className = "", ...rest }) => (
  <textarea className={`nx-textarea ${className}`.trim()} {...rest} />
);
export const Select: FC<any> = ({ children, ...rest }) => (
  <select className="nx-select" {...rest}>{children}</select>
);

/* --------------------------- MultiSelect ------------------------------- */
export const MultiSelect: FC<{
  values: string[];
  options: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  allowCustom?: boolean;
  customPlaceholder?: string;
  missingOptions?: string[];
  missingLabel?: string;
}> = ({ values, options, onChange, placeholder = "", allowCustom = false, customPlaceholder = "", missingOptions = [], missingLabel = "needs inbound" }) => {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const missing = new Set(missingOptions);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const toggle = (opt: string) =>
    onChange(values.includes(opt) ? values.filter((v) => v !== opt) : [...values, opt]);

  const addCustom = () => {
    const v = custom.trim();
    if (!v || values.includes(v)) {
      setCustom("");
      return;
    }
    onChange([...values, v]);
    setCustom("");
  };

  const allOptions = [...new Set([...options, ...values])];

  return (
    <div className="nx-multiselect" ref={ref}>
      <button type="button" className={`nx-ms-control ${open ? "open" : ""}`} onClick={() => setOpen((o) => !o)}>
        {values.length === 0 ? (
          <span className="nx-ms-ph">{placeholder}</span>
        ) : (
          <span className="nx-ms-tags">
            {values.map((v) => (
              <span key={v} className="nx-ms-tag">
                {v}
                <i
                  role="button"
                  aria-hidden
                  onClick={(e) => { e.stopPropagation(); toggle(v); }}
                >×</i>
              </span>
            ))}
          </span>
        )}
        <span className="nx-ms-caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="nx-ms-panel">
          {allOptions.length === 0 ? (
            <div className="nx-ms-empty">—</div>
          ) : (
            allOptions.map((opt) => (
              <div
                key={opt}
                className={`nx-ms-opt ${values.includes(opt) ? "active" : ""}`}
                onClick={() => toggle(opt)}
              >
                <span className="nx-ms-check" aria-hidden>{values.includes(opt) ? "✓" : ""}</span>
                <span>
                  {opt}
                  {missing.has(opt) && (
                    <span className="nx-faint" style={{ marginInlineStart: 6, fontSize: 11 }}>
                      ({missingLabel})
                    </span>
                  )}
                </span>
              </div>
            ))
          )}
          {allowCustom && (
            <div className="nx-ms-custom" style={{ display: "flex", gap: 6, padding: 8, borderTop: "1px solid var(--nx-border)" }}>
              <Input
                value={custom}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setCustom(e.target.value)}
                placeholder={customPlaceholder || "custom tag"}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }}
              />
              <Button size="sm" type="button" onClick={addCustom} disabled={!custom.trim()}>+</Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

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
export const Callout: FC<{ tone?: "info" | "warn" | "danger" | "ok"; title?: string; className?: string; children: ReactNode }> = ({ tone = "info", title, className, children }) => (
  <div className={["nx-callout", tone, className].filter(Boolean).join(" ")}>
    <div>
      {title && <div className="nx-callout-title">{title}</div>}
      <div>{children}</div>
    </div>
  </div>
);

/* ------------------------------ EmptyState ----------------------------- */
export const EmptyState: FC<{ title: string; desc?: string; steps?: string[]; action?: ReactNode }> = ({ title, desc, steps, action }) => (
  <div className="nx-empty">
    <div className="nx-empty-icon" aria-hidden>○</div>
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

/* Accessible icon-only close button shared by Modal and Drawer. */
const CloseButton: FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useTranslation();
  return (
    <button className="nx-btn icon ghost" onClick={onClose} title={t("common.close")} aria-label={t("common.close")}>
      <IcClose />
    </button>
  );
};

/* -------------------------------- Modal -------------------------------- */
export const Modal: FC<{
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode;
  wide?: boolean; formWide?: boolean; hideHead?: boolean;
}> = ({ open, title, onClose, children, footer, wide, formWide, hideHead }) => {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open || typeof document === "undefined") return null;
  const modalCls = ["nx-modal", wide && "wide", formWide && "form-wide"].filter(Boolean).join(" ");
  return createPortal(
    <div className="nx-overlay" onClick={onClose}>
      <div className={modalCls} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {!hideHead && (
        <div className="nx-modal-head">
          <div className="nx-card-title">{title}</div>
          <CloseButton onClose={onClose} />
        </div>
        )}
        <div className="nx-modal-body">{children}</div>
        {footer && <div className="nx-modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
};

/* ------------------------------- Drawer -------------------------------- */
export const Drawer: FC<{
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  overlayClassName?: string;
  drawerClassName?: string;
}> = ({ open, title, onClose, children, wide, overlayClassName = "", drawerClassName = "" }) => {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open || typeof document === "undefined") return null;
  const overlayCls = ["nx-drawer-overlay", overlayClassName].filter(Boolean).join(" ");
  const drawerCls = ["nx-drawer", wide && "wide", drawerClassName].filter(Boolean).join(" ");
  return createPortal(
    <div className={overlayCls} onClick={onClose}>
      <div className={drawerCls} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="nx-drawer-head">
          <div className="nx-card-title">{title}</div>
          <CloseButton onClose={onClose} />
        </div>
        <div className="nx-drawer-body">{children}</div>
      </div>
    </div>,
    document.body,
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
export const Checkbox: FC<{ checked: boolean; onChange?: () => void; label?: string }> = ({ checked, onChange, label }) => (
  <span
    className={`nx-checkbox ${checked ? "on" : ""}`}
    role="checkbox"
    aria-checked={checked}
    aria-label={label}
    tabIndex={onChange ? 0 : -1}
    onClick={onChange}
    onKeyDown={(e) => {
      if (onChange && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        onChange();
      }
    }}
  >
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

/* ------------------------------- Pager --------------------------------- */
/**
 * Client-side pagination for tables whose API returns the full list.
 * Use with `usePagedList`; renders nothing when everything fits on one page.
 */
export function usePagedList<T>(items: T[] | null | undefined, pageSize = 20) {
  const [page, setPage] = useState(0);
  const list = items || [];
  const pages = Math.max(1, Math.ceil(list.length / pageSize));
  const safePage = Math.min(page, pages - 1);
  return {
    page: safePage,
    pages,
    total: list.length,
    slice: list.slice(safePage * pageSize, (safePage + 1) * pageSize),
    setPage,
  };
}

export const Pager: FC<{ page: number; pages: number; onPage: (p: number) => void }> = ({ page, pages, onPage }) => {
  const { t } = useTranslation();
  if (pages <= 1) return null;
  return (
    <div className="nx-row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
      <Button size="sm" disabled={page === 0} onClick={() => onPage(page - 1)}>{t("users.prev")}</Button>
      <span className="nx-faint" style={{ fontSize: 12 }}>{page + 1} / {pages}</span>
      <Button size="sm" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>{t("users.next")}</Button>
    </div>
  );
};

/* ------------------------------ Loading -------------------------------- */
export const Loading: FC<{ label?: string }> = ({ label }) => {
  const { t } = useTranslation();
  return <div className="nx-loading">{label || t("common.loading")}</div>;
};

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
