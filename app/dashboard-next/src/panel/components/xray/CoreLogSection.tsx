import { FC, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { getToken } from "../../api/client";
import { Button, Card, Callout } from "../ui";

/** Live Xray core log viewer (WebSocket /api/core/logs). */
export const CoreLogSection: FC = () => {
  const { t } = useTranslation();
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const boxRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setError("Not authenticated");
      return;
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(
      `${proto}://${window.location.host}/api/core/logs?interval=1&token=${encodeURIComponent(token)}`,
    );
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setError(t("common.error"));
    ws.onmessage = (ev) => {
      const chunk = String(ev.data || "").trim();
      if (!chunk) return;
      setLines((prev) => [...prev.slice(-400), ...chunk.split("\n")]);
    };
    return () => ws.close();
  }, [t]);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [lines]);

  return (
    <Card>
      <div className="nx-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <strong>{t("xray.coreLogs")}</strong>
        <Button size="sm" variant="ghost" onClick={() => setLines([])}>{t("common.clear")}</Button>
      </div>
      {!connected && !error && <Callout tone="info">{t("common.loading")}</Callout>}
      {error && <Callout tone="warn">{error}</Callout>}
      <pre ref={boxRef} className="nx-log-viewer" dir="ltr" style={{ maxHeight: 420, overflow: "auto", fontSize: 12 }}>
        {lines.join("\n") || "—"}
      </pre>
    </Card>
  );
};
