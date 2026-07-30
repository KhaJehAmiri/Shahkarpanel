import { createContext, FC, ReactNode, useContext, useEffect, useState } from "react";
import { api, clearToken, getToken, setUnauthorizedHandler } from "../api/client";
import { AdminInfo, Branding, FeatureFlag } from "../api/types";
import { applyBranding } from "../lib/branding";

const THEME_KEY = "sk_theme";
const EXPERT_KEY = "sk_expert_mode";

interface AppState {
  admin: AdminInfo | null;
  branding: Branding | null;
  flags: Record<string, boolean>;
  loadingAuth: boolean;
  theme: "dark" | "light";
  expertMode: boolean;
  setTheme: (t: "dark" | "light") => void;
  setExpertMode: (v: boolean) => void;
  isEnabled: (flag: string) => boolean;
  hasPermission: (perm: string) => boolean;
  refreshFlags: () => Promise<void>;
  logout: () => void;
  onAuthenticated: () => Promise<void>;
}

const Ctx = createContext<AppState>({} as AppState);
export const useApp = () => useContext(Ctx);

export const AppProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [admin, setAdmin] = useState<AdminInfo | null>(null);
  const [branding, setBranding] = useState<Branding | null>(null);
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [loadingAuth, setLoadingAuth] = useState(true);
  const [theme, setThemeState] = useState<"dark" | "light">(() => {
    if (typeof window === "undefined") return "dark";
    return (localStorage.getItem(THEME_KEY) as "dark" | "light") || "dark";
  });
  const [expertMode, setExpertModeState] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(EXPERT_KEY) === "1";
  });

  const setTheme = (t: "dark" | "light") => {
    setThemeState(t);
    localStorage.setItem(THEME_KEY, t);
    document.documentElement.setAttribute("data-theme", t);
  };

  const setExpertMode = (v: boolean) => {
    setExpertModeState(v);
    localStorage.setItem(EXPERT_KEY, v ? "1" : "0");
  };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const refreshFlags = async () => {
    try {
      const data = await api.get<FeatureFlag[]>("/feature-flags");
      const map: Record<string, boolean> = {};
      data.forEach((f) => (map[f.name] = f.enabled));
      setFlags(map);
    } catch {
      // GET /feature-flags is readable by every authenticated admin, so this
      // only happens on transient errors; keep the previous map.
    }
  };

  const loadBranding = async () => {
    try {
      const b = await api.get<Branding>("/branding/mine");
      setBranding(b);
      applyBranding(b);
    } catch {
      try {
        const b = await api.get<Branding>("/branding");
        setBranding(b);
        applyBranding(b);
      } catch {
        setBranding(null);
      }
    }
  };

  const loadAdmin = async () => {
    try {
      const me = await api.get<AdminInfo>("/admin");
      setAdmin(me);
      await Promise.all([refreshFlags(), loadBranding()]);
    } catch {
      setAdmin(null);
      setBranding(null);
    } finally {
      setLoadingAuth(false);
    }
  };

  const onAuthenticated = async () => {
    setLoadingAuth(true);
    await loadAdmin();
  };

  const logout = () => {
    clearToken();
    setAdmin(null);
    setBranding(null);
    setFlags({});
  };

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken();
      setAdmin(null);
    });
    if (getToken()) {
      loadAdmin();
    } else {
      setLoadingAuth(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isEnabled = (flag: string) => {
    if (flag in flags) return flags[flag];
    // Unknown flags: only sudo sees experimental tabs; resellers/support avoid 404 tabs.
    return !!admin?.is_sudo;
  };

  const hasPermission = (perm: string) => {
    if (admin?.is_sudo) return true;
    return (admin?.permissions || []).includes(perm);
  };

  return (
    <Ctx.Provider
      value={{ admin, branding, flags, loadingAuth, theme, expertMode, setTheme, setExpertMode, isEnabled, hasPermission, refreshFlags, logout, onAuthenticated }}
    >
      {children}
    </Ctx.Provider>
  );
};
