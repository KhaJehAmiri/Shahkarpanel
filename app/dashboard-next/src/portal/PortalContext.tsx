"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { copyToClipboard } from "@/lib/clipboard";
import {
  clearPortalToken,
  getPortalToken,
  PORTAL_UNAUTHORIZED_EVENT,
  portalDelete,
  portalGet,
  portalLogin,
  portalPost,
  portalPut,
  portalUpload,
  setPortalToken,
} from "@/lib/portal-api";
import { detectPortalLang, PortalLang, pt, storePortalLang } from "@/lib/portal-i18n";
import { pickDefaultUsername } from "./format";
import type {
  CardCheckout,
  PaymentCardInfo,
  PortalAccountSummary,
  PortalConfigs,
  PortalOrder,
  PortalPlan,
  PortalProfile,
  PortalTransaction,
  ShopMode,
  ShopStep,
  TabId,
} from "./types";

type PortalCtx = {
  lang: PortalLang;
  rtl: boolean;
  pickLang: (c: PortalLang) => void;
  authed: boolean;
  busy: boolean;
  toast: string;
  showToast: (msg: string) => void;
  tab: TabId;
  setTab: (t: TabId) => void;
  me: PortalProfile | null;
  accounts: PortalAccountSummary[];
  activeUsername: string;
  setActiveUsername: (u: string) => void;
  activeProfile: PortalProfile | null;
  plans: PortalPlan[];
  orders: PortalOrder[];
  transactions: PortalTransaction[];
  txUnreadCount: number;
  txReadCount: number;
  refreshTransactions: () => Promise<void>;
  markTransactionRead: (id: number) => Promise<void>;
  configs: PortalConfigs | null;
  payProviders: string[];
  payMethods: string[];
  cardInfo: PaymentCardInfo | null;
  payCards: PaymentCardInfo[];
  checkoutMethod: "gateway" | "card";
  setCheckoutMethod: (m: "gateway" | "card") => void;
  provider: string;
  setProvider: (p: string) => void;
  cardCheckout: CardCheckout | null;
  setCardCheckout: (c: CardCheckout | null) => void;
  selectCheckoutCard: (cardId: string) => Promise<void>;
  cardNote: string;
  setCardNote: (n: string) => void;
  cardReceipt: File | null;
  setCardReceipt: (f: File | null) => void;
  cardSubmittedOk: boolean;
  setCardSubmittedOk: (v: boolean) => void;
  currencyLabel: string;
  brandTitle: string;
  brandLogo: string;
  shopMode: ShopMode;
  setShopMode: (m: ShopMode) => void;
  shopStep: ShopStep;
  setShopStep: (s: ShopStep) => void;
  newUsername: string;
  setNewUsername: (u: string) => void;
  renewUsername: string;
  setRenewUsername: (u: string) => void;
  supportUrl?: string | null;
  loginUser: string;
  setLoginUser: (u: string) => void;
  password: string;
  setPassword: (p: string) => void;
  loginErr: string;
  submitLogin: (e: React.FormEvent) => Promise<void>;
  logout: () => void;
  mustChangeCredentials: boolean;
  completeSetup: (newUsername: string, newPassword: string) => Promise<void>;
  payPlan: (planId: number, planName?: string) => Promise<void>;
  submitCardPurchase: () => Promise<void>;
  copyCardNumber: () => Promise<void>;
  rotateSub: () => Promise<void>;
  saveCustomSub: () => Promise<void>;
  savePassword: () => Promise<void>;
  deleteAccount: (username: string) => Promise<void>;
  deleteConfirm: string | null;
  setDeleteConfirm: (u: string | null) => void;
  curPw: string;
  setCurPw: (v: string) => void;
  newPw: string;
  setNewPw: (v: string) => void;
  confirmPw: string;
  setConfirmPw: (v: string) => void;
  subMode: "auto" | "custom";
  setSubMode: (m: "auto" | "custom") => void;
  customToken: string;
  setCustomToken: (t: string) => void;
  copyText: (text: string, okMsg?: string) => Promise<void>;
  formatPrice: (amount: number) => string;
  bootstrapping: boolean;
};

const Ctx = createContext<PortalCtx | null>(null);

export function usePortal(): PortalCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePortal outside provider");
  return v;
}

export function PortalProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<PortalLang>("fa");
  const [authed, setAuthed] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [loginUser, setLoginUser] = useState("");
  const [password, setPassword] = useState("");
  const [loginErr, setLoginErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [me, setMe] = useState<PortalProfile | null>(null);
  const [accounts, setAccounts] = useState<PortalAccountSummary[]>([]);
  const [activeUsername, setActiveUsername] = useState("");
  const [activeProfile, setActiveProfile] = useState<PortalProfile | null>(null);
  const [plans, setPlans] = useState<PortalPlan[]>([]);
  const [orders, setOrders] = useState<PortalOrder[]>([]);
  const [transactions, setTransactions] = useState<PortalTransaction[]>([]);
  const [configs, setConfigs] = useState<PortalConfigs | null>(null);
  const [payProviders, setPayProviders] = useState<string[]>([]);
  const [payMethods, setPayMethods] = useState<string[]>([]);
  const [cardInfo, setCardInfo] = useState<PaymentCardInfo | null>(null);
  const [payCards, setPayCards] = useState<PaymentCardInfo[]>([]);
  const [checkoutMethod, setCheckoutMethod] = useState<"gateway" | "card">("gateway");
  const [provider, setProvider] = useState("");
  const [cardCheckout, setCardCheckout] = useState<CardCheckout | null>(null);
  const [cardNote, setCardNote] = useState("");
  const [cardReceipt, setCardReceipt] = useState<File | null>(null);
  const [cardSubmittedOk, setCardSubmittedOk] = useState(false);
  const [currencyLabel, setCurrencyLabel] = useState("");
  const [brandTitle, setBrandTitle] = useState("Shahkar");
  const [brandLogo, setBrandLogo] = useState("/sub-assets/brand/shahkar.png");
  const [toast, setToast] = useState("");
  const [tab, setTab] = useState<TabId>("home");
  const [shopMode, setShopMode] = useState<ShopMode>("renew");
  const [shopStep, setShopStep] = useState<ShopStep>("mode");
  const [newUsername, setNewUsername] = useState("");
  const [renewUsername, setRenewUsername] = useState("");
  const [subMode, setSubMode] = useState<"auto" | "custom">("auto");
  const [customToken, setCustomToken] = useState("");
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // One timer only — back-to-back toasts must not cut each other short.
  const toastTimerRef = useRef<number | null>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimerRef.current != null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => {
      toastTimerRef.current = null;
      setToast("");
    }, 3200);
  }, []);

  const formatPriceFn = useCallback(
    (amount: number) => {
      if (amount === 0) return pt(lang, "free");
      const label = currencyLabel || (lang === "fa" ? "تومان" : "");
      return `${amount.toLocaleString(lang === "fa" ? "fa-IR" : undefined)}${label ? ` ${label}` : ""}`;
    },
    [lang, currencyLabel],
  );

  const loadAccounts = useCallback(async () => {
    try {
      const list = await portalGet<PortalAccountSummary[]>("/portal/accounts");
      setAccounts(list);
      return list;
    } catch {
      setAccounts([]);
      return [] as PortalAccountSummary[];
    }
  }, []);

  const loadTransactions = useCallback(async () => {
    try {
      const list = await portalGet<PortalTransaction[]>("/portal/transactions");
      setTransactions(list);
      try {
        const { setPortalAppBadgeCount } = await import("./lib/portalPwa");
        const unread = list.filter((t) => t.unread !== false).length;
        await setPortalAppBadgeCount(unread);
      } catch {
        /* optional */
      }
    } catch {
      setTransactions([]);
    }
    try {
      setOrders(await portalGet<PortalOrder[]>("/portal/orders"));
    } catch {
      setOrders([]);
    }
  }, []);

  const markTransactionRead = useCallback(async (id: number) => {
    let nextUnread = 0;
    setTransactions((prev) => {
      const next = prev.map((t) => (t.id === id ? { ...t, unread: false } : t));
      nextUnread = next.filter((t) => t.unread !== false).length;
      return next;
    });
    // Update badge immediately with known count (clear only if truly 0).
    try {
      const { setPortalAppBadgeCount } = await import("./lib/portalPwa");
      await setPortalAppBadgeCount(nextUnread);
    } catch {
      /* optional */
    }
    try {
      await portalPost(`/portal/transactions/${id}/read`, {});
      try {
        const { syncPortalAppBadge } = await import("./lib/portalPwa");
        await syncPortalAppBadge();
      } catch {
        /* optional */
      }
    } catch {
      try {
        setTransactions(await portalGet<PortalTransaction[]>("/portal/transactions"));
      } catch {
        /* ignore */
      }
    }
  }, []);

  const configsReqRef = useRef(0);

  const loadConfigs = useCallback(async (username: string) => {
    if (!username) {
      setConfigs(null);
      return;
    }
    const req = ++configsReqRef.current;
    try {
      const data = await portalGet<PortalConfigs>(
        `/portal/accounts/${encodeURIComponent(username)}/configs`,
      );
      if (req === configsReqRef.current) setConfigs(data);
    } catch {
      if (req === configsReqRef.current) setConfigs(null);
    }
  }, []);

  const loadActiveAccount = useCallback(
    async (username: string, opts?: { withConfigs?: boolean }) => {
      if (!username) {
        setActiveProfile(null);
        setConfigs(null);
        return;
      }
      try {
        const profile = await portalGet<PortalProfile>(
          `/portal/accounts/${encodeURIComponent(username)}`,
        );
        setActiveProfile(profile);
        setCustomToken(profile.sub_token || "");
      } catch {
        setActiveProfile(null);
      }
      // Configs are heavy (~0.8s+) — only when Connect/Accounts needs them.
      if (opts?.withConfigs) await loadConfigs(username);
    },
    [loadConfigs],
  );
  const loadSecondaryDashboard = useCallback(async () => {
    const [brandingRes, plansRes, txRes, ordersRes, methodsRes] = await Promise.allSettled([
      portalGet<{
        panel_title?: string;
        primary_color?: string;
        currency_label?: string;
        support_url?: string;
        logo_url?: string;
        favicon_url?: string;
      }>("/portal/branding"),
      portalGet<PortalPlan[]>("/portal/plans"),
      portalGet<PortalTransaction[]>("/portal/transactions"),
      portalGet<PortalOrder[]>("/portal/orders"),
      portalGet<{
        methods: string[];
        gateway_providers: string[];
        card?: PaymentCardInfo | null;
        cards?: PaymentCardInfo[];
      }>("/portal/payment-methods"),
    ]);

    if (brandingRes.status === "fulfilled") {
      const b = brandingRes.value;
      try {
        if (b?.primary_color) {
          document.documentElement.style.setProperty("--p-accent", b.primary_color);
          document.documentElement.style.setProperty("--p-accent-2", b.primary_color);
          const theme = document.querySelector(".portal-theme") as HTMLElement | null;
          theme?.style.setProperty("--p-accent", b.primary_color);
          theme?.style.setProperty("--p-accent-2", b.primary_color);
        }
        const title = (b?.panel_title || "").trim();
        // Ignore leftover smoke/test titles so the desktop shell shows Shahkar.
        const looksLikeSmoke =
          /^smoke[\s_-]/i.test(title) || /\bsmoke\b/i.test(title);
        if (title && !looksLikeSmoke) {
          document.title = title;
          setBrandTitle(title);
        } else {
          document.title = pt(lang, "brand");
          setBrandTitle(pt(lang, "brand"));
        }
        setBrandLogo((b?.logo_url || "").trim() || "/sub-assets/brand/shahkar.png");
        {
          let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null;
          if (!link) {
            link = document.createElement("link");
            link.rel = "icon";
            document.head.appendChild(link);
          }
          link.href = (b?.favicon_url || "").trim() || "/brand/favicon.ico";
        }
        if (b?.currency_label) setCurrencyLabel(b.currency_label);
      } catch {
        /* ignore */
      }
    }

    setPlans(plansRes.status === "fulfilled" ? plansRes.value : []);

    if (txRes.status === "fulfilled") {
      const list = txRes.value;
      setTransactions(list);
      try {
        const { setPortalAppBadgeCount } = await import("./lib/portalPwa");
        const unread = list.filter((t) => t.unread !== false).length;
        await setPortalAppBadgeCount(unread);
      } catch {
        /* optional */
      }
    } else {
      setTransactions([]);
    }
    setOrders(ordersRes.status === "fulfilled" ? ordersRes.value : []);

    if (methodsRes.status === "fulfilled") {
      const methods = methodsRes.value;
      setPayMethods(methods.methods || []);
      setPayProviders(methods.gateway_providers || []);
      setProvider((prev) => prev || methods.gateway_providers?.[0] || "");
      const cardsList = methods.cards?.length
        ? methods.cards
        : methods.card
          ? [methods.card]
          : [];
      setPayCards(cardsList);
      setCardInfo(methods.card || cardsList[0] || null);
      setCheckoutMethod((prev) => {
        if (methods.methods?.includes(prev)) return prev;
        return (methods.methods?.[0] as "gateway" | "card") || "gateway";
      });
    } else {
      setPayMethods([]);
      setPayProviders([]);
      setPayCards([]);
      setCardInfo(null);
    }
  }, [lang]);

  const loadDashboard = useCallback(async () => {
    // Critical path only: identity + accounts — show UI ASAP.
    const [meRes, accountsRes] = await Promise.allSettled([
      portalGet<PortalProfile>("/portal/me"),
      portalGet<PortalAccountSummary[]>("/portal/accounts"),
    ]);
    if (meRes.status !== "fulfilled") {
      throw meRes.reason instanceof Error ? meRes.reason : new Error("unauthorized");
    }
    const portalMe = meRes.value;
    const list = accountsRes.status === "fulfilled" ? accountsRes.value : [];
    setMe(portalMe);
    setAccounts(list);
    const defaultUser = pickDefaultUsername(portalMe, list);
    setActiveUsername((prev) => {
      if (prev && list.some((a) => a.username === prev)) return prev;
      return defaultUser;
    });
    // Shop / history / branding / pay — background, do not block first paint.
    void loadSecondaryDashboard();
  }, [loadSecondaryDashboard]);

  useEffect(() => {
    const l = detectPortalLang();
    setLang(l);
    document.documentElement.lang = l;
    document.documentElement.dir = l === "fa" ? "rtl" : "ltr";
    try {
      const params = new URLSearchParams(window.location.search);
      const qUser = params.get("username");
      if (qUser) setLoginUser(qUser.trim());
      const pay = params.get("pay");
      if (pay === "ok" || pay === "fail" || pay === "status") {
        if (pay === "ok") showToast(pt(l, "payOk"));
        else if (pay === "fail") showToast(pt(l, "payFail"));
        params.delete("pay");
        const qs = params.toString();
        const next = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash || ""}`;
        window.history.replaceState({}, "", next);
      }
    } catch {
      /* ignore */
    }
    if (getPortalToken()) {
      loadDashboard()
        .then(() => setAuthed(true))
        .catch(() => {
          clearPortalToken();
          setAuthed(false);
        })
        .finally(() => setBootstrapping(false));
    } else {
      setBootstrapping(false);
    }
  }, [loadDashboard, showToast]);

  const mustChangeCredentials = Boolean(me?.must_change_credentials);

  const completeSetup = async (newUsername: string, newPassword: string) => {
    setBusy(true);
    try {
      const r = await portalPost<{ access_token: string }>("/portal/complete-setup", {
        new_username: newUsername,
        new_password: newPassword,
      });
      setPortalToken(r.access_token);
      await loadDashboard();
      showToast(pt(lang, "setupDone"));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!authed || !activeUsername) return;
    setConfigs(null);
    void loadActiveAccount(activeUsername, { withConfigs: false });
    setRenewUsername(activeUsername);
  }, [activeUsername, authed, loadActiveAccount]);

  // Defer heavy /configs until the user opens Accounts / Connect.
  useEffect(() => {
    if (!authed || !activeUsername) return;
    if (tab !== "accounts" && tab !== "configs") return;
    void loadConfigs(activeUsername);
  }, [tab, activeUsername, authed, loadConfigs]);
  const pickLang = (code: PortalLang) => {
    setLang(code);
    storePortalLang(code);
    document.documentElement.lang = code;
    document.documentElement.dir = code === "fa" ? "rtl" : "ltr";
    const u = new URL(window.location.href);
    u.searchParams.set("lang", code);
    window.history.replaceState({}, "", u.toString());
  };

  const submitLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginErr("");
    setBusy(true);
    try {
      await portalLogin(loginUser.trim(), password);
      await loadDashboard();
      setAuthed(true);
      setTab("home");
      // Push/badge must not block login spinner
      void import("./lib/portalPwa")
        .then((m) => m.enablePortalPush())
        .catch(() => undefined);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : pt(lang, "loginFailed");
      setLoginErr(msg === "401" ? pt(lang, "loginFailed") : msg);
    } finally {
      setBusy(false);
    }
  };

  const refreshAfterAccountChange = async (selectUsername?: string) => {
    const list = await loadAccounts();
    await loadTransactions();
    // The login account's own quota/expiry may have just changed too.
    try {
      setMe(await portalGet<PortalProfile>("/portal/me"));
    } catch {
      /* keep previous identity */
    }
    const next =
      selectUsername && list.some((a) => a.username === selectUsername)
        ? selectUsername
        : pickDefaultUsername(me || ({ username: "" } as PortalProfile), list);
    setActiveUsername(next);
    if (next) await loadActiveAccount(next);
  };

  const createFreeAccount = async (planId: number) => {
    const uname = newUsername.trim();
    if (uname.length < 3) {
      showToast(pt(lang, "newUsername"));
      return;
    }
    setBusy(true);
    try {
      await portalPost<PortalProfile>("/portal/accounts", { plan_id: planId, username: uname });
      showToast(pt(lang, "accountCreated"));
      setNewUsername("");
      setShopStep("mode");
      await refreshAfterAccountChange(uname);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  /** Direct renew endpoint: free plans, and paid plans billed to the reseller wallet. */
  const renewDirect = async (planId: number, username: string) => {
    setBusy(true);
    try {
      await portalPost(`/portal/accounts/${encodeURIComponent(username)}/renew`, { plan_id: planId });
      showToast(pt(lang, "renewedAccount"));
      setShopStep("mode");
      await refreshAfterAccountChange(username);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : pt(lang, "error");
      showToast(msg.toLowerCase().includes("insufficient") ? pt(lang, "walletError") : msg);
    } finally {
      setBusy(false);
    }
  };

  const payPlan = async (planId: number, planName?: string) => {
    const isBuy = shopMode === "buy";
    const targetRenew = renewUsername || activeUsername;
    if (isBuy && newUsername.trim().length < 3) {
      showToast(pt(lang, "newUsername"));
      return;
    }
    if (!isBuy && !targetRenew) {
      showToast(pt(lang, "selectAccount"));
      return;
    }

    setBusy(true);
    try {
      const useCard = checkoutMethod === "card" && payMethods.includes("card");
      const payProvider = useCard ? "card" : provider || payProviders[0] || "";
      const isFree = plans.find((p) => p.id === planId)?.price === 0;
      if (!isFree && !payProvider) {
        showToast(pt(lang, "noPayMethods"));
        return;
      }

      if (!isBuy && isFree) {
        await renewDirect(planId, targetRenew);
        return;
      }
      if (isBuy && isFree) {
        await createFreeAccount(planId);
        return;
      }
      // No checkout method configured: paid renewals still work when the
      // reseller pays from their wallet — the API answers with a clear reason
      // when they cannot.
      if (payMethods.length === 0) {
        if (isBuy) {
          showToast(pt(lang, "noPayMethods"));
          return;
        }
        await renewDirect(planId, targetRenew);
        return;
      }

      const body: Record<string, string | number> = {
        plan_id: planId,
        provider: payProvider,
        action: isBuy ? "purchase" : "renew",
      };
      if (isBuy) body.new_username = newUsername.trim();
      else body.username = targetRenew;

      const created = await portalPost<{
        payment_id: number;
        confirm_token?: string;
        checkout_url?: string;
        card_id?: string;
        card_number?: string;
        card_holder?: string;
        card_bank?: string;
        cards?: PaymentCardInfo[];
        amount: number;
        provider: string;
        action?: string;
        username?: string;
      }>("/portal/payments", body);

      if (useCard || created.provider === "card") {
        const cardsList =
          created.cards?.length
            ? created.cards
            : payCards.length
              ? payCards
              : created.card_number
                ? [{
                    id: created.card_id,
                    number: created.card_number,
                    holder: created.card_holder || "",
                    bank: created.card_bank || "",
                  }]
                : cardInfo
                  ? [cardInfo]
                  : [];
        setCardCheckout({
          payment_id: created.payment_id,
          amount: created.amount,
          card_id: created.card_id,
          card_number: created.card_number || cardInfo?.number,
          card_holder: created.card_holder || cardInfo?.holder,
          card_bank: created.card_bank || cardInfo?.bank,
          cards: cardsList,
          plan_name: planName,
          action: created.action || (body.action as string),
          username: created.username || (isBuy ? newUsername.trim() : targetRenew),
        });
        setCardNote("");
        setCardReceipt(null);
        setShopStep("pay");
        showToast(pt(lang, "cardReady"));
        return;
      }
      if (created.checkout_url) {
        showToast(pt(lang, "redirectPay"));
        window.location.href = created.checkout_url;
        return;
      }
      if (created.confirm_token) {
        const done = await portalPost<{ username?: string; detail?: string }>(
          `/portal/payments/${created.payment_id}/complete`,
          { confirm_token: created.confirm_token },
        );
        showToast(isBuy ? pt(lang, "purchasedNew") : pt(lang, "renewedAccount"));
        setShopStep("mode");
        await refreshAfterAccountChange(done.username || (isBuy ? newUsername.trim() : targetRenew));
        if (isBuy) setNewUsername("");
        return;
      }
      showToast(isBuy ? pt(lang, "purchasedNew") : pt(lang, "renewedAccount"));
      setShopStep("mode");
      await refreshAfterAccountChange(isBuy ? newUsername.trim() : targetRenew);
      if (isBuy) setNewUsername("");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  const selectCheckoutCard = async (cardId: string) => {
    if (!cardCheckout || !cardId) return;
    if (cardCheckout.card_id === cardId) return;
    setBusy(true);
    try {
      const updated = await portalPut<{
        card_id?: string;
        card_number?: string;
        card_holder?: string;
        card_bank?: string;
        cards?: PaymentCardInfo[];
      }>(`/portal/payments/${cardCheckout.payment_id}/card`, { card_id: cardId });
      setCardCheckout({
        ...cardCheckout,
        card_id: updated.card_id || cardId,
        card_number: updated.card_number || cardCheckout.card_number,
        card_holder: updated.card_holder || cardCheckout.card_holder,
        card_bank: updated.card_bank || cardCheckout.card_bank,
        cards: updated.cards?.length ? updated.cards : cardCheckout.cards,
      });
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  const submitCardPurchase = async () => {
    if (!cardCheckout) return;
    if (!cardReceipt) {
      showToast(pt(lang, "cardReceiptRequired"));
      return;
    }
    if (cardReceipt.size > 15 * 1024 * 1024) {
      showToast(pt(lang, "cardReceiptHint"));
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      if (cardNote.trim()) form.append("note", cardNote.trim());
      form.append("receipt", cardReceipt);
      await portalUpload(`/portal/payments/${cardCheckout.payment_id}/submit`, form);
      showToast(pt(lang, "cardSubmitted"));
      setCardCheckout(null);
      setCardNote("");
      setCardReceipt(null);
      setCardSubmittedOk(true);
      // Stay on the pay step so the "awaiting approval" panel is shown.
      setShopStep("pay");
      await loadAccounts();
      await loadTransactions();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  const copyCardNumber = async () => {
    const num = (cardCheckout?.card_number || cardInfo?.number || "").replace(/\s+/g, "");
    if (!num) return;
    const ok = await copyToClipboard(num);
    showToast(ok ? pt(lang, "cardCopied") : pt(lang, "error"));
  };

  const rotateSub = async () => {
    if (!activeUsername) return;
    setBusy(true);
    try {
      const r = await portalPost<{
        sub_token: string;
        subscription_url: string;
        public_subscription_url: string;
      }>(`/portal/accounts/${encodeURIComponent(activeUsername)}/rotate-sub`, {});
      setActiveProfile((p) =>
        p
          ? {
              ...p,
              sub_token: r.sub_token,
              subscription_url: r.subscription_url,
              public_subscription_url: r.public_subscription_url,
            }
          : p,
      );
      setCustomToken(r.sub_token);
      showToast(pt(lang, "subIdRotated"));
      await loadActiveAccount(activeUsername, { withConfigs: true });
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  const saveCustomSub = async () => {
    if (!activeUsername) return;
    setBusy(true);
    try {
      const r = await portalPost<{
        sub_token: string;
        subscription_url: string;
        public_subscription_url: string;
      }>(`/portal/accounts/${encodeURIComponent(activeUsername)}/sub-token`, {
        token: customToken.trim().toLowerCase(),
      });
      setActiveProfile((p) =>
        p
          ? {
              ...p,
              sub_token: r.sub_token,
              subscription_url: r.subscription_url,
              public_subscription_url: r.public_subscription_url,
            }
          : p,
      );
      setCustomToken(r.sub_token);
      showToast(pt(lang, "subIdUpdated"));
      await loadActiveAccount(activeUsername, { withConfigs: true });
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };
  const savePassword = async () => {
    if (newPw !== confirmPw) {
      showToast(pt(lang, "passwordMismatch"));
      return;
    }
    setBusy(true);
    try {
      const res = await portalPost<{ access_token?: string }>("/portal/password", {
        current_password: curPw,
        new_password: newPw,
      });
      // Changing the password revokes older tokens — adopt the fresh one.
      if (res?.access_token) setPortalToken(res.access_token);
      setCurPw("");
      setNewPw("");
      setConfirmPw("");
      showToast(pt(lang, "passwordSaved"));
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  const deleteAccount = async (username: string) => {
    const acct = accounts.find((a) => a.username === username);
    if (acct?.is_portal_login) {
      showToast(pt(lang, "cannotDeletePortalLogin"));
      setDeleteConfirm(null);
      return;
    }
    setBusy(true);
    try {
      await portalDelete(`/portal/accounts/${encodeURIComponent(username)}`);
      showToast(pt(lang, "accountDeleted"));
      setDeleteConfirm(null);
      const list = await loadAccounts();
      const next = pickDefaultUsername(me || ({ username: "" } as PortalProfile), list);
      setActiveUsername(next);
      if (next) await loadActiveAccount(next);
      else {
        setActiveProfile(null);
        setConfigs(null);
      }
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setBusy(false);
    }
  };

  const resetSession = useCallback(() => {
    clearPortalToken();
    setAuthed(false);
    setMe(null);
    setAccounts([]);
    setActiveUsername("");
    setActiveProfile(null);
    setPlans([]);
    setOrders([]);
    setTransactions([]);
    setConfigs(null);
    setCardCheckout(null);
    setPassword("");
    setTab("home");
    setShopStep("mode");
  }, []);

  const logout = () => {
    resetSession();
  };

  // An expired/revoked token used to leave the app "logged in" with empty
  // cards; every 401 now lands the user back on the login screen.
  const authedRef = useRef(false);
  authedRef.current = authed;
  useEffect(() => {
    const onUnauthorized = () => {
      const wasAuthed = authedRef.current;
      resetSession();
      if (wasAuthed) showToast(pt(lang, "sessionExpired"));
    };
    window.addEventListener(PORTAL_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(PORTAL_UNAUTHORIZED_EVENT, onUnauthorized);
  }, [lang, resetSession, showToast]);

  const txUnreadCount = useMemo(
    () => transactions.filter((t) => t.unread !== false).length,
    [transactions],
  );
  const txReadCount = useMemo(
    () => transactions.filter((t) => t.unread === false).length,
    [transactions],
  );

  const copyText = async (text: string, okMsg?: string) => {
    if (!text) return;
    const ok = await copyToClipboard(text);
    showToast(ok ? okMsg || pt(lang, "copied") : pt(lang, "error"));
  };

  const value = useMemo<PortalCtx>(
    () => ({
      lang,
      rtl: lang === "fa",
      pickLang,
      authed,
      busy,
      toast,
      showToast,
      tab,
      setTab,
      me,
      accounts,
      activeUsername,
      setActiveUsername,
      activeProfile,
      plans,
      orders,
      transactions,
      txUnreadCount,
      txReadCount,
      refreshTransactions: loadTransactions,
      markTransactionRead,
      configs,
      payProviders,
      payMethods,
      cardInfo,
      payCards,
      checkoutMethod,
      setCheckoutMethod,
      provider,
      setProvider,
      cardCheckout,
      setCardCheckout,
      selectCheckoutCard,
      cardNote,
      setCardNote,
      cardReceipt,
      setCardReceipt,
      cardSubmittedOk,
      setCardSubmittedOk,
      currencyLabel,
      brandTitle,
      brandLogo,
      shopMode,
      setShopMode,
      shopStep,
      setShopStep,
      newUsername,
      setNewUsername,
      renewUsername,
      setRenewUsername,
      supportUrl: me?.support_url || activeProfile?.support_url,
      loginUser,
      setLoginUser,
      password,
      setPassword,
      loginErr,
      submitLogin,
      logout,
      mustChangeCredentials,
      completeSetup,
      payPlan,
      submitCardPurchase,
      copyCardNumber,
      rotateSub,
      saveCustomSub,
      savePassword,
      deleteAccount,
      deleteConfirm,
      setDeleteConfirm,
      curPw,
      setCurPw,
      newPw,
      setNewPw,
      confirmPw,
      setConfirmPw,
      subMode,
      setSubMode,
      customToken,
      setCustomToken,
      copyText,
      formatPrice: formatPriceFn,
      bootstrapping,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      lang,
      authed,
      busy,
      toast,
      tab,
      me,
      accounts,
      activeUsername,
      activeProfile,
      plans,
      orders,
      transactions,
      txUnreadCount,
      txReadCount,
      loadTransactions,
      markTransactionRead,
      configs,
      payProviders,
      payMethods,
      cardInfo,
      payCards,
      checkoutMethod,
      provider,
      cardCheckout,
      selectCheckoutCard,
      cardNote,
      cardReceipt,
      cardSubmittedOk,
      currencyLabel,
      brandTitle,
      brandLogo,
      shopMode,
      shopStep,
      newUsername,
      renewUsername,
      loginUser,
      password,
      loginErr,
      deleteConfirm,
      curPw,
      newPw,
      confirmPw,
      subMode,
      customToken,
      formatPriceFn,
      bootstrapping,
      mustChangeCredentials,
      showToast,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
