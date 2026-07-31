export interface PortalAccountSummary {
  username: string;
  status: string;
  used_traffic: number;
  data_limit: number | null;
  expire: number | null;
  online: boolean;
  online_devices: number;
  is_portal_login: boolean;
  public_subscription_url?: string;
  created_at?: string | null;
}

export interface PortalProfile {
  username: string;
  status: string;
  used_traffic: number;
  overage_traffic?: number;
  lifetime_used_traffic?: number;
  data_limit: number | null;
  expire: number | null;
  device_limit?: number | null;
  online_devices?: number;
  public_subscription_url?: string;
  subscription_url?: string;
  client_subscription_url?: string;
  sub_token?: string | null;
  online?: boolean;
  note?: string | null;
  support_url?: string | null;
  created_at?: string | null;
  is_portal_login?: boolean;
  must_change_credentials?: boolean;
}

export interface PortalPlan {
  id: number;
  name: string;
  price: number;
  data_limit: number | null;
  duration_days: number | null;
  device_limit?: number | null;
}

export interface PortalOrder {
  id: number;
  plan_name: string;
  amount: number;
  status: string;
  created_at: string;
}

export interface PortalTransaction {
  id: number;
  kind: string;
  kind_label: string;
  provider: string;
  provider_label: string;
  amount: number;
  amount_label: string;
  status: string;
  status_label: string;
  plan_id?: number | null;
  plan_name?: string | null;
  account?: string | null;
  title: string;
  body: string;
  lines: string[];
  date: string;
  time: string;
  created_at?: string | null;
  completed_at?: string | null;
  unread?: boolean;
  can_pay?: boolean;
  expires_at?: string | null;
}

export interface PortalLinkItem {
  link: string;
  protocol?: string;
  remark?: string;
  region_flag?: string;
  region_name?: string;
  latency_ms?: number | null;
}

export interface PortalSubUrl {
  label: string;
  slug?: string;
  url: string;
  import_url?: string | null;
  recommended?: boolean;
}

export interface PortalNodeLink {
  id: number;
  name: string;
  address?: string;
  region_flag?: string | null;
  region_name?: string | null;
  link?: string | null;
  /** wg-quick INI for official WireGuard app (QR / .conf download). */
  conf?: string | null;
  protocol?: string;
  latency_ms?: number | null;
}

export interface PortalConfigs {
  config_available: boolean;
  block_reason?: string | null;
  public_subscription_url?: string;
  client_subscription_url?: string;
  subscription_urls?: PortalSubUrl[];
  link_items?: PortalLinkItem[];
  links?: string[];
  wireguard_nodes?: PortalNodeLink[];
  singbox_nodes?: PortalNodeLink[];
}

export type TabId = "home" | "accounts" | "shop" | "configs" | "security" | "history";
export type ShopMode = "buy" | "renew";
export type ShopStep = "mode" | "plan" | "pay";
export type Quality = "great" | "ok" | "busy" | "unknown";

export type FriendlyServer = {
  key: string;
  flag: string;
  country: string;
  countryKey: string | null;
  hint: string;
  quality: Quality;
  latencyMs: number | null;
  link: string;
  /** wg-quick body when available (preferred for WireGuard app import). */
  conf?: string;
  technicalTitle: string;
  protocolRaw: string;
};

export type PaymentCardInfo = {
  id?: string;
  number: string;
  holder: string;
  bank: string;
};

export type CardCheckout = {
  payment_id: number;
  amount: number;
  card_id?: string;
  card_number?: string;
  card_holder?: string;
  card_bank?: string;
  cards?: PaymentCardInfo[];
  plan_name?: string;
  action?: string;
  username?: string;
};
