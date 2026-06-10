export type SubTheme = "dark" | "light";

const KEY = "nx_sub_theme";

export function detectSubTheme(): SubTheme {
  if (typeof window === "undefined") return "light";
  const saved = localStorage.getItem(KEY);
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applySubTheme(theme: SubTheme) {
  document.documentElement.setAttribute("data-sub-theme", theme);
  localStorage.setItem(KEY, theme);
}

export function initSubTheme() {
  applySubTheme(detectSubTheme());
}
