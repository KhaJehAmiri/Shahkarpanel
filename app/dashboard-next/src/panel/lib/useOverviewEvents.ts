import { useEffect, useRef, useState } from "react";
import { getToken } from "../api/client";
import type { RealtimeStats, SystemStats } from "../api/types";

export interface LiveTick extends Partial<SystemStats>, Partial<RealtimeStats> {
  kind?: string;
  t?: number;
  fresh?: boolean;
  xray_started?: boolean;
  xray_version?: string;
}

const STALE_MS = 8000;
const FALLBACK_MS = 5000;

function liveUrl(): string {
  const token = getToken() || "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/live?token=${encodeURIComponent(token)}`;
}

function asTick(msg: LiveTick): LiveTick | null {
  if (!msg || msg.kind === "ping" || msg.kind === "empty") return null;
  if (msg.kind && msg.kind !== "tick") return null;
  if (msg.online_users == null && msg.incoming_bandwidth_speed == null) return null;
  return msg;
}

/**
 * Overview live KPIs over WebSocket (1s ticks). HTTP fallback only if the
 * socket drops — never poll /analytics/realtime on a healthy live channel.
 */
export function useOverviewEvents(handlers?: {
  onNodeStatus?: () => void;
  onUserSync?: () => void;
}) {
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [connected, setConnected] = useState(false);
  const [stale, setStale] = useState(false);
  const lastTickAt = useRef(0);
  const openedAt = useRef(0);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    let sock: WebSocket | null = null;
    let closed = false;
    let reconnectTimer = 0;
    let delay = 1000;
    let gen = 0;

    const connect = () => {
      if (closed) return;
      const my = ++gen;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = 0;
      }
      const token = getToken();
      if (!token) {
        setConnected(false);
        setStale(true);
        return;
      }
      const prev = sock;
      sock = null;
      if (prev) {
        prev.onclose = null;
        prev.onerror = null;
        prev.onmessage = null;
        try { prev.close(); } catch { /* ignore */ }
      }
      try {
        sock = new WebSocket(liveUrl());
      } catch {
        setConnected(false);
        setStale(true);
        reconnectTimer = window.setTimeout(connect, delay);
        delay = Math.min(delay * 2, FALLBACK_MS);
        return;
      }
      sock.onopen = () => {
        if (my !== gen) return;
        delay = 1000;
        openedAt.current = Date.now();
        setConnected(true);
      };
      sock.onclose = () => {
        if (closed || my !== gen) return;
        setConnected(false);
        reconnectTimer = window.setTimeout(connect, delay);
        delay = Math.min(delay * 2, FALLBACK_MS);
      };
      sock.onerror = () => {
        try { sock?.close(); } catch { /* ignore */ }
      };
      sock.onmessage = (ev) => {
        if (my !== gen) return;
        let msg: LiveTick | null = null;
        try {
          msg = JSON.parse(String(ev.data || "")) as LiveTick;
        } catch {
          return;
        }
        if (!msg) return;
        if (msg.kind === "ping") return;
        if (msg.kind === "node.status") {
          handlersRef.current?.onNodeStatus?.();
          return;
        }
        if (msg.kind === "user.sync") {
          handlersRef.current?.onUserSync?.();
          return;
        }
        const next = asTick(msg);
        if (next) {
          lastTickAt.current = Date.now();
          setStale(false);
          setTick(next);
        }
      };
    };

    connect();
    const staleId = window.setInterval(() => {
      const now = Date.now();
      const tickAge = lastTickAt.current ? now - lastTickAt.current : 0;
      const openAge = openedAt.current ? now - openedAt.current : 0;
      if (lastTickAt.current ? tickAge > STALE_MS : openAge > STALE_MS) {
        setStale(true);
      }
    }, 5000);
    const onVis = () => {
      if (document.visibilityState !== "visible") return;
      if (sock && sock.readyState === WebSocket.OPEN) return;
      connect();
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      closed = true;
      document.removeEventListener("visibilitychange", onVis);
      window.clearInterval(staleId);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (sock) {
        sock.onclose = null;
        try { sock.close(); } catch { /* ignore */ }
      }
    };
  }, []);

  return { tick, connected, stale };
}
