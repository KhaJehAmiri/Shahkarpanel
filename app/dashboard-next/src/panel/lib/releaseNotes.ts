import { UpdateCheck } from "../api/types";

const SEEN_KEY = "nx_seen_releases";
const PENDING_KEY = "nx_pending_whats_new";

export type PendingWhatsNew = {
  version: string;
  notes: string[];
};

export function releaseNotesForLang(check: UpdateCheck | null, lang: string): string[] {
  if (!check) return [];
  const i18n = check.release_notes_i18n;
  if (i18n && typeof i18n === "object") {
    const list = i18n[lang] || i18n.en || i18n.fa;
    if (Array.isArray(list) && list.length) return list.filter(Boolean);
  }
  const raw = check.release_notes || check.changelog_md || "";
  return raw.split("\n").map((l) => l.trim()).filter(Boolean);
}

export function hasSeenRelease(version: string): boolean {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    const seen: string[] = raw ? JSON.parse(raw) : [];
    return seen.includes(version);
  } catch {
    return false;
  }
}

export function markReleaseSeen(version: string): void {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    const seen: string[] = raw ? JSON.parse(raw) : [];
    if (!seen.includes(version)) {
      seen.push(version);
      localStorage.setItem(SEEN_KEY, JSON.stringify(seen.slice(-20)));
    }
  } catch {
    localStorage.setItem(SEEN_KEY, JSON.stringify([version]));
  }
}

export function stashPendingWhatsNew(payload: PendingWhatsNew): void {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(payload));
}

export function consumePendingWhatsNew(): PendingWhatsNew | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PENDING_KEY);
    const parsed = JSON.parse(raw) as PendingWhatsNew;
    if (parsed?.version && Array.isArray(parsed.notes)) return parsed;
  } catch {
    sessionStorage.removeItem(PENDING_KEY);
  }
  return null;
}
