import { createContext, FC, ReactNode, useContext, useEffect, useState } from "react";
import { api, clearToken, getToken, setUnauthorizedHandler } from "../api/client";
import { AdminInfo, FeatureFlag } from "../api/types";

const THEME_KEY = "nx_theme";

interface AppState {
  admin: AdminInfo | null;
  flags: Record<string, boolean>;
  loadingAuth: boolean;
  theme: "dark" | "light";
  setTheme: (t: "dark" | "light") => void;
  isEnabled: (flag: string) => boolean;
  refreshFlags: () => Promise<void>;
  logout: () => void;
  onAuthenticated: () => Promise<void>;
}

const Ctx = createContext<AppState>({} as AppState);
export const useApp = () => useContext(Ctx);

export const AppProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [admin, setAdmin] = useState<AdminInfo | null>(null);
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [loadingAuth, setLoadingAuth] = useState(true);
  const [theme, setThemeState] = useState<"dark" | "light">(
    (localStorage.getItem(THEME_KEY) as "dark" | "light") || "dark"
  );

  const setTheme = (t: "dark" | "light") => {
    setThemeState(t);
    localStorage.setItem(THEME_KEY, t);
    document.documentElement.setAttribute("data-theme", t);
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
      // Non-sudo admins cannot read flags; assume capabilities are available
      // and let individual endpoints return 404 when disabled.
      setFlags({});
    }
  };

  const loadAdmin = async () => {
    try {
      const me = await api.get<AdminInfo>("/admin");
      setAdmin(me);
      await refreshFlags();
    } catch {
      setAdmin(null);
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
    // Unknown flags (non-sudo) default to enabled so the UI shows the page;
    // the API still enforces the real state.
    return flag in flags ? flags[flag] : true;
  };

  return (
    <Ctx.Provider
      value={{ admin, flags, loadingAuth, theme, setTheme, isEnabled, refreshFlags, logout, onAuthenticated }}
    >
      {children}
    </Ctx.Provider>
  );
};
