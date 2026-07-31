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
    className={`sk-btn ${variant} ${size === "sm" ? "sm" : ""} ${className}`}
  >
    {children}
  </button>
);

/* -------------------------------- Card --------------------------------- */
export const Card: FC<{ children: ReactNode; className?: string; pad0?: boolean; style?: React.CSSProperties }> = ({ children, className = "", pad0, style }) => (
  <div className={`sk-card ${pad0 ? "pad0 sk-card-table" : "sk-glass-card"} ${className}`} style={style}>{children}</div>
);

export const CardHead: FC<{ title: string; desc?: string; actions?: ReactNode }> = ({ title, desc, actions }) => (
  <div className="sk-card-head">
    <div>
      <div className="sk-card-title">{title}</div>
      {desc && <div className="sk-card-desc">{desc}</div>}
    </div>
    {actions && <div className="sk-row">{actions}</div>}
  </div>
);

/* -------------------------------- Stat --------------------------------- */
export const Stat: FC<{ label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode }> = ({ label, value, sub, icon }) => (
  <div className="sk-stat">
    <div className="sk-stat-label">{icon}{label}</div>
    <div className="sk-stat-value">{value}</div>
    {sub && <div className="sk-stat-sub">{sub}</div>}
  </div>
);

/* -------------------------------- Pill --------------------------------- */
export const Pill: FC<{ children: ReactNode; tone?: "ok" | "danger" | "warn" | "info" | "accent" | "default"; dot?: boolean }> = ({ children, tone = "default", dot }) => (
  <span className={`sk-pill ${tone}`}>{dot && <span className="sk-dot" />}{children}</span>
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
    className={`sk-toggle ${on ? "on" : ""}`}
    onClick={() => !disabled && onChange(!on)}
    style={disabled ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
  >
    <span className="sk-toggle-knob" />
  </button>
);

/* ------------------------------- Inputs -------------------------------- */
export const Field: FC<{ label?: string; hint?: string; children: ReactNode }> = ({ label, hint, children }) => (
  <div className="sk-field">
    {label && <label className="sk-label">{label}</label>}
    {children}
    {hint && <span className="sk-hint">{hint}</span>}
  </div>
);

export const Input: FC<InputHTMLAttributes<HTMLInputElement>> = ({
  className = "",
  onClick,
  type,
  ...props
}) => (
  <input
    {...props}
    type={type}
    className={`sk-input${type === "date" ? " sk-input-date" : ""} ${className}`.trim()}
    onClick={(e) => {
      onClick?.(e);
      if (e.defaultPrevented) return;
      if (type !== "date" || props.disabled || props.readOnly) return;
      const el = e.currentTarget as HTMLInputElement & { showPicker?: () => void };
      try {
        el.showPicker?.();
      } catch {
        /* NotAllowedError / unsupported — native tap still works where possible */
      }
    }}
  />
);
export const Textarea: FC<any> = ({ className = "", ...rest }) => (
  <textarea className={`sk-textarea ${className}`.trim()} {...rest} />
);
export const Select: FC<any> = ({ children, ...rest }) => (
  <select className="sk-select" {...rest}>{children}</select>
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
    <div className="sk-multiselect" ref={ref}>
      <button type="button" className={`sk-ms-control ${open ? "open" : ""}`} onClick={() => setOpen((o) => !o)}>
        {values.length === 0 ? (
          <span className="sk-ms-ph">{placeholder}</span>
        ) : (
          <span className="sk-ms-tags">
            {values.map((v) => (
              <span key={v} className="sk-ms-tag">
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
        <span className="sk-ms-caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="sk-ms-panel">
          {allOptions.length === 0 ? (
            <div className="sk-ms-empty">—</div>
          ) : (
            allOptions.map((opt) => (
              <div
                key={opt}
                className={`sk-ms-opt ${values.includes(opt) ? "active" : ""}`}
                onClick={() => toggle(opt)}
              >
                <span className="sk-ms-check" aria-hidden>{values.includes(opt) ? "✓" : ""}</span>
                <span>
                  {opt}
                  {missing.has(opt) && (
                    <span className="sk-faint" style={{ marginInlineStart: 6, fontSize: 11 }}>
                      ({missingLabel})
                    </span>
                  )}
                </span>
              </div>
            ))
          )}
          {allowCustom && (
            <div className="sk-ms-custom" style={{ display: "flex", gap: 6, padding: 8, borderTop: "1px solid var(--sk-border)" }}>
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
  <div className="sk-tabs">
    {tabs.map((t) => (
      <button key={t.id} className={`sk-tab ${active === t.id ? "active" : ""}`} onClick={() => onChange(t.id)}>
        {t.label}
      </button>
    ))}
  </div>
);

/* ------------------------------- Callout ------------------------------- */
export const Callout: FC<{ tone?: "info" | "warn" | "danger" | "ok"; title?: string; className?: string; children: ReactNode }> = ({ tone = "info", title, className, children }) => (
  <div className={["sk-callout", tone, className].filter(Boolean).join(" ")}>
    <div>
      {title && <div className="sk-callout-title">{title}</div>}
      <div>{children}</div>
    </div>
  </div>
);

/* ------------------------------ EmptyState ----------------------------- */
export const EmptyState: FC<{ title: string; desc?: string; steps?: string[]; action?: ReactNode }> = ({ title, desc, steps, action }) => (
  <div className="sk-empty">
    <div className="sk-empty-icon" aria-hidden>○</div>
    <div className="sk-empty-title">{title}</div>
    {desc && <div className="sk-empty-desc">{desc}</div>}
    {steps && steps.length > 0 && (
      <ol className="sk-empty-steps">
        {steps.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
    )}
    {action && <div className="sk-empty-action">{action}</div>}
  </div>
);

/** Desktop table + mobile card list. CSS toggles visibility at ≤760px. */
export const ResponsiveData: FC<{ table: ReactNode; cards: ReactNode }> = ({ table, cards }) => (
  <>
    <div className="sk-data-desktop">{table}</div>
    <div className="sk-mlist" role="list">{cards}</div>
  </>
);

export const MCard: FC<{
  title: ReactNode;
  subtitle?: ReactNode;
  badge?: ReactNode;
  leading?: ReactNode;
  fields?: Array<{ label: ReactNode; value: ReactNode; hideEmpty?: boolean }>;
  actions?: ReactNode;
  onClick?: () => void;
}> = ({ title, subtitle, badge, leading, fields, actions, onClick }) => {
  const visible = (fields || []).filter((f) => !f.hideEmpty || (f.value != null && f.value !== "" && f.value !== "—"));
  return (
    <article
      className={`sk-mcard${onClick ? " is-clickable" : ""}`}
      role="listitem"
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="sk-mcard-top">
        {leading ? <div className="sk-mcard-leading" onClick={(e) => e.stopPropagation()}>{leading}</div> : null}
        <div className="sk-mcard-head">
          <div className="sk-mcard-title">{title}</div>
          {subtitle ? <div className="sk-mcard-sub">{subtitle}</div> : null}
        </div>
        {badge ? <div className="sk-mcard-badge">{badge}</div> : null}
      </div>
      {visible.length > 0 && (
        <dl className="sk-mcard-fields">
          {visible.map((f, i) => (
            <div key={i} className="sk-mcard-field">
              <dt>{f.label}</dt>
              <dd>{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {actions ? (
        <div className="sk-mcard-actions" onClick={(e) => e.stopPropagation()}>{actions}</div>
      ) : null}
    </article>
  );
};

/* Accessible icon-only close button shared by Modal and Drawer. */
const CloseButton: FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useTranslation();
  return (
    <button className="sk-btn icon ghost" onClick={onClose} title={t("common.close")} aria-label={t("common.close")}>
      <IcClose />
    </button>
  );
};

/** Ignore overlay dismiss briefly after open — blocks the opening click/tap from
 *  instantly closing portaled drawers/modals (common on touch devices). */
function useOverlayDismissGuard(open: boolean) {
  const armedRef = useRef(false);
  useEffect(() => {
    if (!open) {
      armedRef.current = false;
      return;
    }
    armedRef.current = false;
    const id = window.setTimeout(() => {
      armedRef.current = true;
    }, 120);
    return () => window.clearTimeout(id);
  }, [open]);

  return useCallback(
    (onClose: () => void) => () => {
      if (!armedRef.current) return;
      onClose();
    },
    [],
  );
}

/* -------------------------------- Modal -------------------------------- */
export const Modal: FC<{
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode;
  wide?: boolean; formWide?: boolean; hideHead?: boolean; className?: string;
  dismissOnOverlay?: boolean; overlayClassName?: string; subtitle?: ReactNode;
}> = ({ open, title, onClose, children, footer, wide, formWide, hideHead, className,
  dismissOnOverlay = true, overlayClassName = "", subtitle,
}) => {
  const guardedDismiss = useOverlayDismissGuard(open);
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;
  const modalCls = ["sk-modal", wide && "wide", formWide && "form-wide", className].filter(Boolean).join(" ");
  const overlayCls = ["sk-overlay", overlayClassName].filter(Boolean).join(" ");
  return createPortal(
    <div className={overlayCls} onClick={dismissOnOverlay ? guardedDismiss(onClose) : undefined}>
      <div className={modalCls} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {!hideHead && (
        <div className="sk-modal-head">
          <div className="sk-modal-head-text">
            <div className="sk-modal-title">{title}</div>
            {subtitle ? <div className="sk-modal-subtitle">{subtitle}</div> : null}
          </div>
          <CloseButton onClose={onClose} />
        </div>
        )}
        <div className="sk-modal-body">{children}</div>
        {footer && <div className="sk-modal-foot">{footer}</div>}
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
  hideHead?: boolean;
  overlayClassName?: string;
  drawerClassName?: string;
}> = ({ open, title, onClose, children, wide, hideHead, overlayClassName = "", drawerClassName = "" }) => {
  const guardedDismiss = useOverlayDismissGuard(open);
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;
  const overlayCls = ["sk-drawer-overlay", overlayClassName].filter(Boolean).join(" ");
  const drawerCls = ["sk-drawer", wide && "wide", drawerClassName].filter(Boolean).join(" ");
  return createPortal(
    <div className={overlayCls} onClick={guardedDismiss(onClose)}>
      <div className={drawerCls} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        {!hideHead && (
          <div className="sk-drawer-head">
            <div className="sk-card-title">{title}</div>
            <CloseButton onClose={onClose} />
          </div>
        )}
        <div className="sk-drawer-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
};

/* ------------------------------ SectionHelp ----------------------------- */
export const SectionHelp: FC<{ title: ReactNode; children: ReactNode; tone?: "info" | "warn" | "ok" }> = ({ title, children, tone = "info" }) => (
  <div className={`sk-help ${tone}`}>
    <div className="sk-help-mark" aria-hidden>?</div>
    <div className="sk-help-body">
      <div className="sk-help-title">{title}</div>
      <div className="sk-help-text">{children}</div>
    </div>
  </div>
);

/* ------------------------------- HelpTip -------------------------------- */
export const HelpTip: FC<{ text: ReactNode; placement?: "top" | "bottom" }> = ({ text, placement = "top" }) => {
  const { t } = useTranslation();
  return (
    <span className={`sk-tip sk-tip-${placement}`} tabIndex={0} aria-label={t("common.help")}>
      <span className="sk-tip-mark" aria-hidden>?</span>
      <span className="sk-tip-bubble" role="tooltip">{text}</span>
    </span>
  );
};

/* ----------------------------- Checkbox -------------------------------- */
export const Checkbox: FC<{ checked: boolean; onChange?: () => void; label?: string }> = ({ checked, onChange, label }) => (
  <span
    className={`sk-checkbox ${checked ? "on" : ""}`}
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
    <div className="sk-copy-field">
      {label && <label className="sk-label">{label}</label>}
      <div className="sk-copy-row">
        {multiline ? (
          <textarea className={`sk-input ${mono ? "sk-mono" : ""}`} readOnly value={value} rows={3} onFocus={(e) => e.target.select()} />
        ) : (
          <input className={`sk-input ${mono ? "sk-mono" : ""}`} readOnly value={value} onFocus={(e) => e.target.select()} />
        )}
        <button type="button" className={`sk-copy-btn ${copied ? "ok" : ""}`} onClick={copy} aria-label={t("common.copy")}>
          {copied ? <IcCheck size={14} /> : <span aria-hidden style={{ fontSize: 14 }}>⧉</span>}
          <span className="sk-copy-btn-label">{copied ? t("common.copied") : t("common.copy")}</span>
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
    <button type="button" onClick={copy} className={`sk-btn ${size === "sm" ? "sm" : ""} ${className}`} aria-label={copyLabel} title={copyLabel}>
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
    <div className="sk-bar" title={`${v.toFixed(0)}%`}>
      <div className={`sk-bar-fill ${tone}`} style={{ width: `${v}%` }} />
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

/* ------------------------------- Pager --------------------------------- */
function buildPageWindow(page: number, pages: number): (number | "ellipsis")[] {
  if (pages <= 7) {
    return Array.from({ length: pages }, (_, i) => i + 1);
  }
  const cur = page + 1;
  const near = new Set(
    [1, pages, cur - 1, cur, cur + 1].filter((n) => n >= 1 && n <= pages),
  );
  const sorted = [...near].sort((a, b) => a - b);
  const window: (number | "ellipsis")[] = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) window.push("ellipsis");
    window.push(sorted[i]);
  }
  return window;
}

/**
 * Pagination with first/last, numbered pages, and jump-to-page input.
 * Pass `summary` for a left-side label (e.g. "Showing 1–12 of 5222").
 */
export const Pager: FC<{
  page: number;
  pages: number;
  onPage: (p: number) => void;
  summary?: ReactNode;
}> = ({ page, pages, onPage, summary }) => {
  const { t } = useTranslation();
  const [jump, setJump] = useState("");

  if (pages <= 1) return null;

  const goTo = (p: number) => {
    onPage(Math.max(0, Math.min(pages - 1, p)));
  };

  const submitJump = () => {
    const n = parseInt(jump.trim(), 10);
    if (!Number.isFinite(n) || n < 1 || n > pages) return;
    goTo(n - 1);
    setJump("");
  };

  const pageWindow = buildPageWindow(page, pages);

  const controls = (
    <div className="sk-pager">
      <Button
        size="sm"
        variant="ghost"
        disabled={page === 0}
        onClick={() => goTo(0)}
        title={t("pagination.first")}
        aria-label={t("pagination.first")}
      >
        «
      </Button>
      <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => goTo(page - 1)}>
        {t("users.prev")}
      </Button>
      <div className="sk-pager-nums">
        {pageWindow.map((item, idx) =>
          item === "ellipsis" ? (
            <span key={`e-${idx}`} className="sk-pager-ellipsis">…</span>
          ) : (
            <button
              key={item}
              type="button"
              className={`sk-pager-num ${item === page + 1 ? "active" : ""}`}
              onClick={() => goTo(item - 1)}
              aria-current={item === page + 1 ? "page" : undefined}
            >
              {item}
            </button>
          ),
        )}
      </div>
      <Button size="sm" variant="ghost" disabled={page + 1 >= pages} onClick={() => goTo(page + 1)}>
        {t("users.next")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={page + 1 >= pages}
        onClick={() => goTo(pages - 1)}
        title={t("pagination.last")}
        aria-label={t("pagination.last")}
      >
        »
      </Button>
      <form
        className="sk-pager-jump"
        onSubmit={(e) => { e.preventDefault(); submitJump(); }}
      >
        <Input
          type="number"
          min={1}
          max={pages}
          value={jump}
          onChange={(e) => setJump(e.target.value)}
          placeholder={t("pagination.page")}
          aria-label={t("pagination.goTo")}
          dir="ltr"
        />
        <Button size="sm" variant="ghost" type="submit" disabled={!jump.trim()}>
          {t("pagination.go")}
        </Button>
      </form>
    </div>
  );

  if (summary) {
    return (
      <div className="sk-pager-bar">
        <span className="sk-faint" style={{ fontSize: 12 }}>{summary}</span>
        {controls}
      </div>
    );
  }

  return <div style={{ marginTop: 10 }}>{controls}</div>;
};

/* ------------------------------ Loading -------------------------------- */
export const Loading: FC<{ label?: string }> = ({ label }) => {
  const { t } = useTranslation();
  return <div className="sk-loading">{label || t("common.loading")}</div>;
};

export const SkeletonRows: FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 4 }) => (
  <div className="sk-stack">
    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} className="sk-row" style={{ gap: 16 }}>
        {Array.from({ length: cols }).map((__, j) => (
          <div key={j} className="sk-skel" style={{ height: 16, flex: j === 0 ? 2 : 1 }} />
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
      <div className="sk-toasts" role="region" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`sk-toast ${t.kind}`} role="status">
            <span className="sk-toast-icon" aria-hidden>{TOAST_ICON[t.kind]}</span>
            <span className="sk-toast-msg">{t.msg}</span>
            <button className="sk-toast-x" onClick={() => dismiss(t.id)} aria-label={tr("common.dismiss")}>×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
};
