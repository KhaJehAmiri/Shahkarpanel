"use client";

import { UseFormReturn } from "react-hook-form";
import { cn } from "@/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { FieldRow, inputClass } from "../shared/FieldRow";
import { CollapsibleSection } from "../shared/CollapsibleSection";
import { KeyValueRepeater } from "../shared/KeyValueRepeater";
import { TagInput } from "../shared/TagInput";
import { fieldError } from "../useInboundForm";
import type { InboundFormState, NetworkType, ProtocolDefinition, XHTTPMode } from "../types";
import { findProtocolDef } from "../types";
import { DOMAIN_STRATEGIES, MKCP_HEADER_TYPES } from "../types";
import { RawStreamPanel } from "../stream/RawStreamPanel";
import { SockoptPanel } from "../stream/SockoptPanel";
import { TcpMaskRepeater } from "../stream/TcpMaskRepeater";

interface Props {
  form: UseFormReturn<InboundFormState>;
  errors: Record<string, string>;
  protocols: ProtocolDefinition[];
  setNetwork: (n: NetworkType) => void;
}

const TRANSPORTS: { id: NetworkType; label: string }[] = [
  { id: "raw", label: "RAW" },
  { id: "ws", label: "WebSocket" },
  { id: "grpc", label: "gRPC" },
  { id: "xhttp", label: "XHTTP" },
  { id: "httpupgrade", label: "HTTPUpgrade" },
  { id: "mkcp", label: "mKCP" },
  { id: "quic", label: "XHTTP H3" },
  { id: "http", label: "HTTP/H2" },
];

function XhttpFieldRows({
  isDownload,
  watch,
  setValue,
  errors,
}: {
  isDownload: boolean;
  watch: UseFormReturn<InboundFormState>["watch"];
  setValue: UseFormReturn<InboundFormState>["setValue"];
  errors: Record<string, string>;
}) {

  return (
    <>
      {!isDownload && (
        <FieldRow label="Path" required error={fieldError(errors, "xhttpSettings.path")}>
          <input className={inputClass} value={watch("xhttpSettings.path")} onChange={(e) => setValue("xhttpSettings.path", e.target.value)} />
        </FieldRow>
      )}
      {isDownload && (
        <FieldRow label="Path">
          <input
            className={inputClass}
            value={(watch("xhttpSettings.downloadSettings")?.path as string) || ""}
            onChange={(e) =>
              setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), path: e.target.value })
            }
          />
        </FieldRow>
      )}
      <FieldRow label="Host">
        <input
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.host || "" : watch("xhttpSettings.host")}
          onChange={(e) => {
            if (isDownload) {
              setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), host: e.target.value });
            } else {
              setValue("xhttpSettings.host", e.target.value);
            }
          }}
        />
      </FieldRow>
      {!isDownload && (
        <>
          <FieldRow label="Mode">
            <Select
              value={watch("xhttpSettings.mode")}
              onValueChange={(v) => setValue("xhttpSettings.mode", v as XHTTPMode)}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">auto</SelectItem>
                <SelectItem value="stream-one">stream-one</SelectItem>
                <SelectItem value="stream-up">stream-up</SelectItem>
                <SelectItem value="packet-up">packet-up</SelectItem>
              </SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="No SSE Header"><Switch checked={watch("xhttpSettings.noSSEHeader")} onCheckedChange={(v) => setValue("xhttpSettings.noSSEHeader", v)} /></FieldRow>
          <FieldRow label="No gRPC Header"><Switch checked={watch("xhttpSettings.noGRPCHeader")} onCheckedChange={(v) => setValue("xhttpSettings.noGRPCHeader", v)} /></FieldRow>
        </>
      )}
      <FieldRow label="Max Each Post Bytes">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.scMaxEachPostBytes || 0 : watch("xhttpSettings.scMaxEachPostBytes")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), scMaxEachPostBytes: n });
            else setValue("xhttpSettings.scMaxEachPostBytes", n);
          }}
        />
      </FieldRow>
      <FieldRow label="Max Buffered Posts">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.scMaxBufferedPosts || 0 : watch("xhttpSettings.scMaxBufferedPosts")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), scMaxBufferedPosts: n });
            else setValue("xhttpSettings.scMaxBufferedPosts", n);
          }}
        />
      </FieldRow>
      <FieldRow label="Max Concurrent Posts">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.scMaxConcurrentPosts || 0 : watch("xhttpSettings.scMaxConcurrentPosts")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), scMaxConcurrentPosts: n });
            else setValue("xhttpSettings.scMaxConcurrentPosts", n);
          }}
        />
      </FieldRow>
      <FieldRow label="Min Posts Interval (ms)">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.scMinPostsIntervalMs || 0 : watch("xhttpSettings.scMinPostsIntervalMs")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), scMinPostsIntervalMs: n });
            else setValue("xhttpSettings.scMinPostsIntervalMs", n);
          }}
        />
      </FieldRow>
      <FieldRow label="Stream-Up Server Secs">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.scStreamUpServerSecs || 0 : watch("xhttpSettings.scStreamUpServerSecs")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), scStreamUpServerSecs: n });
            else setValue("xhttpSettings.scStreamUpServerSecs", n);
          }}
        />
      </FieldRow>
      <FieldRow label="Server Max Header Bytes">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.serverMaxHeaderBytes || 0 : watch("xhttpSettings.serverMaxHeaderBytes")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), serverMaxHeaderBytes: n });
            else setValue("xhttpSettings.serverMaxHeaderBytes", n);
          }}
        />
      </FieldRow>
      <FieldRow label="Keep Alive Period">
        <input
          type="number"
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.keepAlivePeriod || 0 : watch("xhttpSettings.keepAlivePeriod")}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10) || 0;
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), keepAlivePeriod: n });
            else setValue("xhttpSettings.keepAlivePeriod", n);
          }}
        />
      </FieldRow>
      <FieldRow label="X Padding Bytes">
        <input
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.xPaddingBytes || "" : watch("xhttpSettings.xPaddingBytes")}
          onChange={(e) => {
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), xPaddingBytes: e.target.value });
            else setValue("xhttpSettings.xPaddingBytes", e.target.value);
          }}
        />
      </FieldRow>
      <FieldRow label="Uplink HTTP Method">
        <input
          className={inputClass}
          value={isDownload ? watch("xhttpSettings.downloadSettings")?.uplinkHTTPMethod || "" : watch("xhttpSettings.uplinkHTTPMethod")}
          onChange={(e) => {
            if (isDownload) setValue("xhttpSettings.downloadSettings", { ...watch("xhttpSettings.downloadSettings"), uplinkHTTPMethod: e.target.value });
            else setValue("xhttpSettings.uplinkHTTPMethod", e.target.value);
          }}
          placeholder="POST"
        />
      </FieldRow>
    </>
  );
}

export function Step4Stream({ form, errors, protocols, setNetwork }: Props) {
  const { watch, setValue } = form;
  const protocol = watch("protocol");
  const network = watch("network");
  const xhttpMode = watch("xhttpSettings.mode");
  const protocolDef = findProtocolDef(protocols, protocol);
  if (!protocolDef?.hasStream) return null;

  const isTransportActive = (tid: NetworkType) => {
    if (tid === "quic") return network === "xhttp" && xhttpMode === "stream-one";
    return network === tid;
  };

  return (
    <div className="px-6 py-4">
      <FieldRow label="Transmission">
        <div className="flex flex-wrap gap-2">
          {TRANSPORTS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setNetwork(t.id)}
              className={cn(
                "rounded-lg border px-3 py-2 text-xs font-medium transition",
                isTransportActive(t.id)
                  ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                  : "border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--accent)]/50",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </FieldRow>

      {network === "raw" && <RawStreamPanel form={form} />}

      {network === "ws" && (
        <>
          <FieldRow label="Path" required error={fieldError(errors, "wsSettings.path")}>
            <input className={inputClass} value={watch("wsSettings.path")} onChange={(e) => setValue("wsSettings.path", e.target.value)} />
          </FieldRow>
          <FieldRow label="Host" hint="Override Host header">
            <input className={inputClass} value={watch("wsSettings.host")} onChange={(e) => setValue("wsSettings.host", e.target.value)} />
          </FieldRow>
          <CollapsibleSection title="Custom Headers">
            <KeyValueRepeater
              value={watch("wsSettings.extraHeaders")}
              onChange={(v) => setValue("wsSettings.extraHeaders", v)}
            />
          </CollapsibleSection>
          <FieldRow label="Heartbeat Period" hint="0 = disabled">
            <input type="number" className={inputClass} value={watch("wsSettings.heartbeatPeriod")} onChange={(e) => setValue("wsSettings.heartbeatPeriod", parseInt(e.target.value, 10) || 0)} />
          </FieldRow>
          <FieldRow label="Max Early Data">
            <input type="number" className={inputClass} value={watch("wsSettings.maxEarlyData")} onChange={(e) => setValue("wsSettings.maxEarlyData", parseInt(e.target.value, 10) || 0)} />
          </FieldRow>
          <FieldRow label="Early Data Header Name">
            <input className={inputClass} value={watch("wsSettings.earlyDataHeaderName")} onChange={(e) => setValue("wsSettings.earlyDataHeaderName", e.target.value)} />
          </FieldRow>
          <FieldRow label="Browser Forwarding">
            <Switch checked={watch("wsSettings.browserForwarding")} onCheckedChange={(v) => setValue("wsSettings.browserForwarding", v)} />
          </FieldRow>
          <FieldRow label="Accept Proxy Protocol">
            <Switch checked={watch("wsSettings.acceptProxyProtocol")} onCheckedChange={(v) => setValue("wsSettings.acceptProxyProtocol", v)} />
          </FieldRow>
        </>
      )}

      {network === "grpc" && (
        <>
          <FieldRow label="Service Name" required error={fieldError(errors, "grpcSettings.serviceName")}>
            <input className={inputClass} value={watch("grpcSettings.serviceName")} onChange={(e) => setValue("grpcSettings.serviceName", e.target.value)} />
          </FieldRow>
          <FieldRow label="Authority">
            <input className={inputClass} value={watch("grpcSettings.authority")} onChange={(e) => setValue("grpcSettings.authority", e.target.value)} />
          </FieldRow>
          <FieldRow label="User Agent">
            <input className={inputClass} value={watch("grpcSettings.userAgent")} onChange={(e) => setValue("grpcSettings.userAgent", e.target.value)} />
          </FieldRow>
          <FieldRow label="Multi Mode"><Switch checked={watch("grpcSettings.multiMode")} onCheckedChange={(v) => setValue("grpcSettings.multiMode", v)} /></FieldRow>
          <FieldRow label="Idle Timeout"><input type="number" className={inputClass} value={watch("grpcSettings.idleTimeout")} onChange={(e) => setValue("grpcSettings.idleTimeout", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          <FieldRow label="Health Check Timeout"><input type="number" className={inputClass} value={watch("grpcSettings.healthCheckTimeout")} onChange={(e) => setValue("grpcSettings.healthCheckTimeout", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          <FieldRow label="Permit Without Stream"><Switch checked={watch("grpcSettings.permitWithoutStream")} onCheckedChange={(v) => setValue("grpcSettings.permitWithoutStream", v)} /></FieldRow>
          <FieldRow label="Initial Windows Size"><input type="number" className={inputClass} value={watch("grpcSettings.initialWindowsSize")} onChange={(e) => setValue("grpcSettings.initialWindowsSize", parseInt(e.target.value, 10) || 0)} /></FieldRow>
        </>
      )}

      {network === "xhttp" && (
        <>
          <XhttpFieldRows isDownload={false} watch={watch} setValue={setValue} errors={errors} />
          <CollapsibleSection title="Xmux Settings">
            <FieldRow label="Max Concurrency"><input type="number" className={inputClass} value={watch("xhttpSettings.xmux.maxConcurrency")} onChange={(e) => setValue("xhttpSettings.xmux.maxConcurrency", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="Max Connections"><input type="number" className={inputClass} value={watch("xhttpSettings.xmux.maxConnections")} onChange={(e) => setValue("xhttpSettings.xmux.maxConnections", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="C Max Reuse Times"><input type="number" className={inputClass} value={watch("xhttpSettings.xmux.cMaxReuseTimes")} onChange={(e) => setValue("xhttpSettings.xmux.cMaxReuseTimes", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="H Max Request Times"><input type="number" className={inputClass} value={watch("xhttpSettings.xmux.hMaxRequestTimes")} onChange={(e) => setValue("xhttpSettings.xmux.hMaxRequestTimes", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="H Max Reusable Secs"><input type="number" className={inputClass} value={watch("xhttpSettings.xmux.hMaxReusableSecs")} onChange={(e) => setValue("xhttpSettings.xmux.hMaxReusableSecs", parseInt(e.target.value, 10) || 0)} /></FieldRow>
            <FieldRow label="H Keep Alive Period"><input type="number" className={inputClass} value={watch("xhttpSettings.xmux.hKeepAlivePeriod")} onChange={(e) => setValue("xhttpSettings.xmux.hKeepAlivePeriod", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          </CollapsibleSection>
          <CollapsibleSection title="Download Settings">
            <XhttpFieldRows isDownload watch={watch} setValue={setValue} errors={errors} />
          </CollapsibleSection>
        </>
      )}

      {network === "httpupgrade" && (
        <>
          <FieldRow label="Path" required error={fieldError(errors, "httpupgradeSettings.path")}>
            <input className={inputClass} value={watch("httpupgradeSettings.path")} onChange={(e) => setValue("httpupgradeSettings.path", e.target.value)} />
          </FieldRow>
          <FieldRow label="Host">
            <input className={inputClass} value={watch("httpupgradeSettings.host")} onChange={(e) => setValue("httpupgradeSettings.host", e.target.value)} />
          </FieldRow>
          <CollapsibleSection title="Custom Headers">
            <KeyValueRepeater
              value={watch("httpupgradeSettings.extraHeaders")}
              onChange={(v) => setValue("httpupgradeSettings.extraHeaders", v)}
            />
          </CollapsibleSection>
          <FieldRow label="Accept Proxy Protocol"><Switch checked={watch("httpupgradeSettings.acceptProxyProtocol")} onCheckedChange={(v) => setValue("httpupgradeSettings.acceptProxyProtocol", v)} /></FieldRow>
        </>
      )}

      {network === "mkcp" && (
        <>
          <FieldRow label="MTU"><input type="number" className={inputClass} value={watch("mkcpSettings.mtu")} onChange={(e) => setValue("mkcpSettings.mtu", parseInt(e.target.value, 10) || 1350)} /></FieldRow>
          <FieldRow label="TTI"><input type="number" className={inputClass} value={watch("mkcpSettings.tti")} onChange={(e) => setValue("mkcpSettings.tti", parseInt(e.target.value, 10) || 50)} /></FieldRow>
          <FieldRow label="Uplink Capacity"><input type="number" className={inputClass} value={watch("mkcpSettings.uplinkCapacity")} onChange={(e) => setValue("mkcpSettings.uplinkCapacity", parseInt(e.target.value, 10) || 5)} /></FieldRow>
          <FieldRow label="Downlink Capacity"><input type="number" className={inputClass} value={watch("mkcpSettings.downlinkCapacity")} onChange={(e) => setValue("mkcpSettings.downlinkCapacity", parseInt(e.target.value, 10) || 20)} /></FieldRow>
          <FieldRow label="Congestion"><Switch checked={watch("mkcpSettings.congestion")} onCheckedChange={(v) => setValue("mkcpSettings.congestion", v)} /></FieldRow>
          <FieldRow label="Read Buffer (MB)"><input type="number" className={inputClass} value={watch("mkcpSettings.readBufferSize")} onChange={(e) => setValue("mkcpSettings.readBufferSize", parseInt(e.target.value, 10) || 2)} /></FieldRow>
          <FieldRow label="Write Buffer (MB)"><input type="number" className={inputClass} value={watch("mkcpSettings.writeBufferSize")} onChange={(e) => setValue("mkcpSettings.writeBufferSize", parseInt(e.target.value, 10) || 2)} /></FieldRow>
          <FieldRow label="CWND Multiplier"><input type="number" className={inputClass} value={watch("mkcpSettings.cwnd")} onChange={(e) => setValue("mkcpSettings.cwnd", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          <FieldRow label="Max Sending Window"><input type="number" className={inputClass} value={watch("mkcpSettings.maxSendingWindow")} onChange={(e) => setValue("mkcpSettings.maxSendingWindow", parseInt(e.target.value, 10) || 0)} /></FieldRow>
          <FieldRow label="Header Type">
            <Select value={watch("mkcpSettings.header.type")} onValueChange={(v) => setValue("mkcpSettings.header.type", v as typeof MKCP_HEADER_TYPES[number])}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{MKCP_HEADER_TYPES.map((h) => <SelectItem key={h} value={h}>{h}</SelectItem>)}</SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="Header Domain"><input className={inputClass} value={watch("mkcpSettings.header.domain")} onChange={(e) => setValue("mkcpSettings.header.domain", e.target.value)} /></FieldRow>
          <FieldRow label="Seed"><input className={inputClass} value={watch("mkcpSettings.seed")} onChange={(e) => setValue("mkcpSettings.seed", e.target.value)} /></FieldRow>
          <TcpMaskRepeater form={form} udpMode />
        </>
      )}

      {network === "http" && (
        <>
          <FieldRow label="Path"><input className={inputClass} value={watch("httpTransportSettings.path")} onChange={(e) => setValue("httpTransportSettings.path", e.target.value)} /></FieldRow>
          <FieldRow label="Host">
            <TagInput value={watch("httpTransportSettings.host")} onChange={(v) => setValue("httpTransportSettings.host", v)} placeholder="example.com" />
          </FieldRow>
        </>
      )}

      <SockoptPanel form={form} />
      {network !== "mkcp" && <TcpMaskRepeater form={form} />}
    </div>
  );
}
