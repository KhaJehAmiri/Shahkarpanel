"use client";

import {
  createContext, FC, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import { useApp } from "../context/AppContext";

/**
 * The Copilot ("همیار") is a guided assistant that lives beside every page.
 *
 * It does two jobs:
 *  1. Holds the open/closed state of the assistant panel and which guided
 *     journey (recipe) is active, persisted per-admin in localStorage.
 *  2. Acts as a tiny one-shot *intent bus* so a guided step can ask a page to
 *     do something (e.g. open the "create user" modal). Pages call
 *     `consumeIntent()` on mount/poll and clear it.
 */

export type CopilotIntent =
  | "create-user"
  | "create-wg-user"
  | "add-node"
  | "add-node-ssh"
  | "add-wg-node"
  | "open-inbounds"
  | null;

interface CopilotState {
  open: boolean;
  setOpen: (v: boolean) => void;
  activeRecipe: string | null;
  setActiveRecipe: (id: string | null) => void;
  dismissed: boolean;
  dismiss: () => void;
  completedRecipes: Record<string, boolean>;
  markComplete: (id: string) => void;
  /** Set a one-shot intent and navigate to a hash route. */
  requestIntent: (intent: CopilotIntent, hashRoute?: string) => void;
  /** Read and clear the pending intent if it matches `name`. */
  consumeIntent: (name: Exclude<CopilotIntent, null>) => boolean;
}

const Ctx = createContext<CopilotState>({} as CopilotState);
export const useCopilot = () => useContext(Ctx);

const lsKey = (username: string | undefined, suffix: string) =>
  `nx_copilot_${username || "anon"}_${suffix}`;

export const CopilotProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const { admin } = useApp();
  const username = admin?.username;

  const [open, setOpen] = useState(false);
  const [activeRecipe, setActiveRecipe] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [completedRecipes, setCompletedRecipes] = useState<Record<string, boolean>>({});
  const intentRef = useRef<CopilotIntent>(null);

  // Load persisted state when the admin becomes known.
  useEffect(() => {
    if (!username) return;
    try {
      setDismissed(localStorage.getItem(lsKey(username, "dismissed")) === "1");
      const c = localStorage.getItem(lsKey(username, "completed"));
      setCompletedRecipes(c ? JSON.parse(c) : {});
    } catch { /* ignore */ }
  }, [username]);

  const dismiss = useCallback(() => {
    setDismissed(true);
    setOpen(false);
    if (username) localStorage.setItem(lsKey(username, "dismissed"), "1");
  }, [username]);

  const markComplete = useCallback((id: string) => {
    setCompletedRecipes((prev) => {
      const next = { ...prev, [id]: true };
      if (username) localStorage.setItem(lsKey(username, "completed"), JSON.stringify(next));
      return next;
    });
  }, [username]);

  const requestIntent = useCallback((intent: CopilotIntent, hashRoute?: string) => {
    intentRef.current = intent;
    setOpen(false);
    if (hashRoute) {
      // HashRouter — navigating updates the hash; pages read the intent on mount.
      window.location.hash = hashRoute;
    }
  }, []);

  const consumeIntent = useCallback((name: Exclude<CopilotIntent, null>) => {
    if (intentRef.current === name) {
      intentRef.current = null;
      return true;
    }
    return false;
  }, []);

  const value = useMemo<CopilotState>(() => ({
    open, setOpen, activeRecipe, setActiveRecipe, dismissed, dismiss,
    completedRecipes, markComplete, requestIntent, consumeIntent,
  }), [open, activeRecipe, dismissed, dismiss, completedRecipes, markComplete, requestIntent, consumeIntent]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
};
