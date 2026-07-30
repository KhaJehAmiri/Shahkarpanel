import { FC, ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { IcMore } from "./icons";

export type TableMenuItem = {
  id: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
};

/** Compact ⋯ menu for dense tables — portaled so it is never clipped. */
export const TableRowMenu: FC<{
  items: TableMenuItem[];
  label?: string;
}> = ({ items, label }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; openUp: boolean } | null>(null);

  const place = () => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const menuW = 210;
    const menuH = Math.min(320, 16 + items.length * 38);
    const pad = 8;
    const openUp = r.bottom + menuH + pad > window.innerHeight && r.top > menuH + pad;
    const left = Math.min(Math.max(pad, r.right - menuW), window.innerWidth - menuW - pad);
    const top = openUp ? r.top - pad : r.bottom + pad;
    setPos({ top, left, openUp });
  };

  useEffect(() => {
    if (!open) return;
    place();
    const onDoc = (e: MouseEvent) => {
      const n = e.target as Node;
      if (btnRef.current?.contains(n) || menuRef.current?.contains(n)) return;
      setOpen(false);
    };
    const onReposition = () => place();
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open, items.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!items.length) return null;

  const menu = open && pos && typeof document !== "undefined"
    ? createPortal(
        <div
          ref={menuRef}
          className={`sk-reseller-menu sk-reseller-menu--fixed${pos.openUp ? " is-up" : ""}`}
          role="menu"
          style={{
            top: pos.openUp ? undefined : pos.top,
            bottom: pos.openUp ? window.innerHeight - pos.top : undefined,
            left: pos.left,
          }}
        >
          {items.map((item, i) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className={`sk-reseller-menu-item${item.danger ? " is-danger" : ""}`}
              onClick={() => {
                if (item.disabled) return;
                setOpen(false);
                item.onClick();
              }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>,
        document.body,
      )
    : null;

  return (
    <div className="sk-ra-menu">
      <button
        ref={btnRef}
        type="button"
        className="sk-ra-icon-btn"
        title={label || t("common.actions")}
        aria-label={label || t("common.actions")}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <IcMore className="sk-ico" />
      </button>
      {menu}
    </div>
  );
};
