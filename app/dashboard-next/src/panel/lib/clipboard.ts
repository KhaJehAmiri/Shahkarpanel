// Safe clipboard copy that works on both HTTPS and plain HTTP.
// The async Clipboard API only works in secure contexts (HTTPS / localhost),
// so we fall back to a hidden textarea + document.execCommand("copy").
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard &&
      typeof window !== "undefined" &&
      (window.isSecureContext ?? false)
    ) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the textarea fallback
  }

  if (typeof document === "undefined") return false;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  ta.style.left = "-1000px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  let ok = false;
  try {
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}
