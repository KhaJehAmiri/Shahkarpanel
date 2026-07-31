"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, ChevronLeft, Clock3, X, XCircle } from "lucide-react";
import { PortalLang, pt } from "@/lib/portal-i18n";
import { usePortal } from "../PortalContext";
import { PageHeader } from "../components/Shell";
import type { PortalTransaction } from "../types";

function toneForStatus(status: string): "ok" | "warn" | "danger" | "neutral" {
  if (status === "completed" || status === "paid" || status === "applied") return "ok";
  if (status === "awaiting_review" || status === "pending" || status === "submitted") return "warn";
  if (status === "rejected" || status === "failed" || status === "cancelled" || status === "expired") {
    return "danger";
  }
  return "neutral";
}

function StatusIcon({ tone }: { tone: ReturnType<typeof toneForStatus> }) {
  if (tone === "ok") return <CheckCircle2 size={18} aria-hidden />;
  if (tone === "danger") return <XCircle size={18} aria-hidden />;
  return <Clock3 size={18} aria-hidden />;
}

function formatExpires(lang: PortalLang, expiresAt?: string | null): string | null {
  if (!expiresAt) return null;
  try {
    const d = new Date(expiresAt);
    if (Number.isNaN(d.getTime())) return null;
    return new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : lang === "zh" ? "zh-CN" : lang === "ru" ? "ru-RU" : "en-GB", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(d);
  } catch {
    return null;
  }
}

function TxRow({
  tx,
  lang,
  onOpen,
}: {
  tx: PortalTransaction;
  lang: PortalLang;
  onOpen: (tx: PortalTransaction) => void;
}) {
  const tone = toneForStatus(tx.status);
  const unread = tx.unread !== false;
  return (
    <button
      type="button"
      className={`p-tx-row is-${tone}${unread ? " is-unread" : " is-read"}`}
      onClick={() => onOpen(tx)}
    >
      <span className={`p-tx-icon is-${tone}`} aria-hidden>
        <StatusIcon tone={tone} />
      </span>
      <span className="p-tx-main">
        <strong className="p-tx-row-title">
          {unread ? <span className="p-tx-dot" aria-hidden /> : null}
          {tx.title}
        </strong>
        <span className="p-tx-row-meta">
          {tx.provider_label}
          {tx.kind_label ? ` · ${tx.kind_label}` : ""}
          {tx.can_pay ? ` · ${pt(lang, "txPayNow")}` : ""}
        </span>
      </span>
      <span className="p-tx-side">
        <span className="p-tx-row-amount">{tx.amount_label}</span>
        <span className="p-tx-row-time">
          {tx.date} {tx.time}
        </span>
      </span>
      <ChevronLeft className="p-tx-chevron" size={16} aria-hidden />
    </button>
  );
}

function TxDetailModal({
  tx,
  onClose,
  lang,
}: {
  tx: PortalTransaction;
  onClose: () => void;
  lang: PortalLang;
}) {
  const { markTransactionRead, currencyLabel, resumePayment, busy } = usePortal();
  const tone = toneForStatus(tx.status);
  const currency = currencyLabel || (lang === "fa" ? "تومان" : "");
  const [mounted, setMounted] = useState(false);
  const expiresLabel = formatExpires(lang, tx.expires_at);

  useEffect(() => {
    setMounted(true);
    void markTransactionRead(tx.id);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.classList.add("p-tx-modal-open");
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      document.documentElement.classList.remove("p-tx-modal-open");
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose, markTransactionRead, tx.id]);

  const rows: { label: string; value: string }[] = [
    { label: pt(lang, "txAmount"), value: `${tx.amount_label}${currency ? ` ${currency}` : ""}` },
    { label: pt(lang, "txMethod"), value: tx.provider_label || tx.provider },
    { label: pt(lang, "txType"), value: tx.kind_label || tx.kind },
    ...(tx.plan_name ? [{ label: pt(lang, "txPlan"), value: tx.plan_name }] : []),
    ...(tx.account ? [{ label: pt(lang, "txAccount"), value: tx.account }] : []),
    { label: pt(lang, "txDate"), value: tx.date },
    { label: pt(lang, "txTime"), value: tx.time },
    { label: pt(lang, "txStatus"), value: tx.status_label },
    ...(expiresLabel && (tx.can_pay || tx.status === "pending" || tx.status === "expired")
      ? [{ label: pt(lang, "txExpiresAt"), value: expiresLabel }]
      : []),
  ];

  if (!mounted) return null;

  const host =
    (typeof document !== "undefined" &&
      (document.querySelector(".portal-theme") as HTMLElement | null)) ||
    document.body;

  const onPay = async () => {
    onClose();
    await resumePayment(tx.id);
  };

  return createPortal(
    <div
      className="p-tx-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="p-tx-modal-title"
      onClick={onClose}
    >
      <div className="p-tx-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="p-tx-sheet-top">
          <div className="p-tx-sheet-handle" aria-hidden />
          <button
            type="button"
            className="p-tx-sheet-close"
            aria-label={pt(lang, "close")}
            onClick={onClose}
          >
            <X size={18} />
          </button>

          <div className={`p-tx-sheet-hero is-${tone}`}>
            <span className={`p-tx-icon is-${tone} is-lg`} aria-hidden>
              <StatusIcon tone={tone} />
            </span>
            <h2 id="p-tx-modal-title">{tx.title}</h2>
            <p className="p-tx-sheet-amount">
              {tx.amount_label}
              {currency ? ` ${currency}` : ""}
            </p>
            <span className={`p-tx-pill is-${tone}`}>{tx.status_label}</span>
            {tx.can_pay ? (
              <p className="p-muted" style={{ marginTop: 10, fontSize: 13 }}>
                {pt(lang, "txPayHint")}
              </p>
            ) : null}
            {tx.status === "expired" ? (
              <p className="p-muted" style={{ marginTop: 10, fontSize: 13 }}>
                {pt(lang, "txExpiredHint")}
              </p>
            ) : null}
          </div>
        </div>

        <div className="p-tx-sheet-scroll">
          <dl className="p-tx-detail-list">
            {rows.map((r) => (
              <div key={r.label} className="p-tx-detail-row">
                <dt>{r.label}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="p-tx-sheet-foot">
          {tx.can_pay ? (
            <button
              type="button"
              className="p-btn p-tx-sheet-done"
              disabled={busy}
              onClick={() => void onPay()}
            >
              {busy ? pt(lang, "loading") : pt(lang, "txPayNow")}
            </button>
          ) : null}
          <button type="button" className="p-btn ghost p-tx-sheet-done" onClick={onClose}>
            {pt(lang, "close")}
          </button>
        </div>
      </div>
    </div>,
    host,
  );
}

export function HistoryView() {
  const { lang, transactions, refreshTransactions, txUnreadCount, txReadCount } = usePortal();
  const [selected, setSelected] = useState<PortalTransaction | null>(null);

  useEffect(() => {
    void refreshTransactions();
  }, [refreshTransactions]);

  const hint =
    transactions.length > 0
      ? `${pt(lang, "txUnread")}: ${txUnreadCount} · ${pt(lang, "txRead")}: ${txReadCount}`
      : pt(lang, "historyHint");

  return (
    <div className="p-stack p-tx-page">
      <PageHeader title={pt(lang, "historyTitle")} hint={hint} />

      {transactions.length === 0 ? (
        <div className="p-tx-empty">
          <Clock3 size={28} aria-hidden />
          <p>{pt(lang, "noOrders")}</p>
        </div>
      ) : (
        <section className="p-tx-list" aria-label={pt(lang, "historyTitle")}>
          {transactions.map((tx) => (
            <TxRow key={tx.id} tx={tx} lang={lang} onOpen={setSelected} />
          ))}
        </section>
      )}

      {selected ? (
        <TxDetailModal tx={selected} onClose={() => setSelected(null)} lang={lang} />
      ) : null}
    </div>
  );
}
