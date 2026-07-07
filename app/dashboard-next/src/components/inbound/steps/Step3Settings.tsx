"use client";

import { UseFormReturn } from "react-hook-form";
import { isKnownProtocol, type InboundFormState, type ProtocolDefinition } from "../types";
import { VlessSettings } from "../protocol-settings/VlessSettings";
import { VmessSettings } from "../protocol-settings/VmessSettings";
import { TrojanSettings } from "../protocol-settings/TrojanSettings";
import { ShadowsocksSettings } from "../protocol-settings/ShadowsocksSettings";
import { HttpSettings } from "../protocol-settings/HttpSettings";
import { SocksSettings } from "../protocol-settings/SocksSettings";
import { MixedSettings } from "../protocol-settings/MixedSettings";
import { WireGuardSettings } from "../protocol-settings/WireGuardSettings";
import { Hysteria2SettingsPanel, AmneziaWgSettings } from "../protocol-settings/Hysteria2Settings";
import { TunSettings } from "../protocol-settings/TunSettings";
import { DokodemoSettings } from "../protocol-settings/DokodemoSettings";
import { FallbackJsonEditor } from "../protocol-settings/FallbackJsonEditor";

interface Props {
  form: UseFormReturn<InboundFormState>;
  protocols: ProtocolDefinition[];
  errors: Record<string, string>;
  showFlow: boolean;
  onGenerateWgKeys?: () => Promise<void>;
}

export function Step3Settings({ form, protocols, errors, showFlow, onGenerateWgKeys }: Props) {
  const protocol = form.watch("protocol");
  const def = protocols.find((p) => p.id === protocol);

  if (!isKnownProtocol(protocols, protocol)) {
    return (
      <div className="px-6 py-4">
        <FallbackJsonEditor form={form} protocolLabel={def?.label ?? protocol} errors={errors} />
      </div>
    );
  }

  return (
    <div className="px-6 py-4">
      {protocol === "vless" && (
        <VlessSettings
          form={form}
          showFlow={showFlow}
          showFallbackHint={form.watch("security") === "none"}
        />
      )}
      {protocol === "vmess" && <VmessSettings form={form} errors={errors} />}
      {protocol === "trojan" && <TrojanSettings form={form} errors={errors} />}
      {protocol === "shadowsocks" && <ShadowsocksSettings form={form} errors={errors} />}
      {protocol === "http" && <HttpSettings form={form} />}
      {protocol === "socks" && <SocksSettings form={form} />}
      {protocol === "mixed" && <MixedSettings form={form} />}
      {protocol === "wireguard" && <WireGuardSettings form={form} errors={errors} onGenerateKeys={onGenerateWgKeys} />}
      {protocol === "hysteria" && <Hysteria2SettingsPanel form={form} errors={errors} />}
      {protocol === "amneziawg" && <AmneziaWgSettings form={form} errors={errors} onGenerateWgKeys={onGenerateWgKeys} />}
      {protocol === "tun" && <TunSettings form={form} errors={errors} />}
      {protocol === "dokodemo-door" && <DokodemoSettings form={form} errors={errors} />}
    </div>
  );
}
