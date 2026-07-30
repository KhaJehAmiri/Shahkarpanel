export interface AdminInfo {
  username: string;
  is_sudo: boolean;
  role?: string | null;
  permissions?: string[];
  max_users?: number | null;
  max_nodes?: number | null;
  tenant_id?: number | null;
  telegram_id?: number | null;
  discord_webhook?: string | null;
  centralpay_enabled?: boolean;
  card_enabled?: boolean;
}

export interface SystemStats {
  version: string;
  mem_total: number;
  mem_used: number;
  disk_total?: number;
  disk_used?: number;
  cpu_cores: number;
  cpu_usage: number;
  total_user: number;
  online_users: number;
  users_active: number;
  users_disabled: number;
  users_expired: number;
  users_limited: number;
  users_on_hold: number;
  incoming_bandwidth: number;
  outgoing_bandwidth: number;
  incoming_bandwidth_speed: number;
  outgoing_bandwidth_speed: number;
  bandwidth_source?: string;
  os_uptime?: number;
  xray_uptime?: number;
  node_uptime?: number;
}

export interface CoreStats {
  version: string;
  started: boolean;
  logs_websocket: string;
  startup_error?: string | null;
  failed_inbound_tag?: string | null;
  failed_port?: number | null;
}

export interface UserItem {
  username: string;
  status: string;
  used_traffic: number;
  overage_traffic?: number;
  data_limit: number | null;
  expire: number | null;
  online_at: string | null;
  online?: boolean;
  data_limit_reset_strategy?: string;
  note?: string;
  admin?: { username: string } | null;
  proxies?: Record<string, any>;
  inbounds?: Record<string, string[]>;
  links?: string[];
  link_items?: Array<{
    link: string;
    protocol: string;
    remark: string;
    region_flag?: string;
    region_name?: string;
    address_hint?: string;
  }>;
  subscription_url?: string;
  public_subscription_url?: string;
  client_subscription_url?: string;
  subscription_profile_title?: string;
  subscription_urls?: Array<{
    label: string;
    slug: string;
    url: string;
    import_url?: string;
    export_mode: string;
    inbound_tag?: string | null;
    recommended?: boolean;
  }>;
  portal_enabled?: boolean;
  client_profile?: string | null;
  routing_preset?: string | null;
  dns_policy?: { preset?: string } | Record<string, unknown> | null;
  session_limit_minutes?: number | null;
  speed_limit_up?: number | null;
  speed_limit_down?: number | null;
  device_limit?: number | null;
  sub_token?: string | null;
  sub_revoked_at?: string | null;
}

export type ClientProfile = "gamer" | "trader" | "normal";

export interface DedicatedIPItem {
  id: number;
  address: string;
  node_id?: number | null;
  user_id?: number | null;
  username?: string | null;
  assigned_at?: string | null;
}

export interface DedicatedIPPool {
  total: number;
  assigned: number;
  free: number;
  items: DedicatedIPItem[];
}

export interface NodeSingBoxConfig {
  certificate_path?: string | null;
  key_path?: string | null;
  sni?: string | null;
  clash_api_port?: number;
  clash_api_secret?: string | null;
  hysteria2_enabled?: boolean;
  hysteria2_port?: number | null;
  hysteria2_up_mbps?: number | null;
  hysteria2_down_mbps?: number | null;
  hysteria2_obfs_password?: string | null;
  tuic_enabled?: boolean;
  tuic_port?: number | null;
  tuic_congestion_control?: string;
  anytls_enabled?: boolean;
  anytls_port?: number | null;
  tls_trusted?: boolean;
  tls_issuer?: string | null;
  tls_expires_at?: string | null;
  tls_le_domain?: string | null;
  tls_le_kind?: string | null;
}

export interface SingBoxTLSStatus {
  present: boolean;
  trusted: boolean;
  issuer?: string | null;
  expires_at?: string | null;
  tls_le_domain?: string | null;
  tls_le_kind?: string | null;
}

export interface AmneziaWGParams {
  awg_jc?: number | null;
  awg_jmin?: number | null;
  awg_jmax?: number | null;
  awg_s1?: number | null;
  awg_s2?: number | null;
  awg_s3?: number | null;
  awg_s4?: number | null;
  awg_h1?: number | null;
  awg_h2?: number | null;
  awg_h3?: number | null;
  awg_h4?: number | null;
  sg_wire_enabled?: boolean;
  sg_wire_preset_rev?: string | null;
}

export interface InboundInfo {
  tag: string;
  protocol: string;
  network: string;
  tls: string;
  port: number | string;
  ss_method?: string | null;
}

export type InboundsByProtocol = Record<string, InboundInfo[]>;

export interface UsersResponse {
  users: UserItem[];
  total: number;
}

export interface NodeItem {
  id: number;
  name: string;
  address: string;
  port: number;
  api_port: number;
  status: string;
  xray_version?: string | null;
  message?: string | null;
  usage_coefficient: number;
  region?: string | null;
  group_id?: number | null;
  capacity?: number | null;
  latency_ms?: number | null;
  core_kind?: string;
  warp_enabled?: boolean;
  warp_tag?: string | null;
  provision_status?: string | null;
  provision_message?: string | null;
  provision_progress?: number | null;
  provision_step?: string | null;
  control_tunneled?: boolean;
  wireguard?: ({
    public_key?: string | null;
    endpoint?: string | null;
    listen_port?: number;
    plain_enabled?: boolean;
    awg_enabled?: boolean;
    awg_listen_port?: number;
    awg_public_key?: string | null;
    awg_endpoint?: string | null;
    direct_listen_port?: number | null;
    xray_wg_enabled?: boolean;
    xray_wg_listen_port?: number | null;
    xray_wg_mtu?: number;
    xray_wg_noise?: Record<string, unknown> | null;
    sg_wire_enabled?: boolean;
  } & AmneziaWGParams) | null;
  singbox?: NodeSingBoxConfig | null;
}

export interface Tenant {
  id: number;
  slug: string;
  name: string;
  enabled: boolean;
  owner_admin_id?: number | null;
  max_users?: number | null;
  max_nodes?: number | null;
  byo_node_discount_percent: number;
}

export interface Branding {
  panel_title?: string | null;
  logo_url?: string | null;
  favicon_url?: string | null;
  primary_color?: string | null;
  support_url?: string | null;
  sub_profile_title?: string | null;
  domain?: string | null;
  panel_url?: string | null;
  /** Subscription URI path (default ``sub``), e.g. ``v2ray``. */
  sub_path?: string | null;
  /** Subscription listen port (default ``443``), e.g. ``2096``. */
  sub_port?: number | null;
}

export interface TunnelHealthCheck {
  kind?: string;
  node_id?: number;
  connected?: boolean;
  address?: string;
  port?: number;
  reachable?: boolean;
  error?: string;
}

export interface TunnelHealth {
  healthy: boolean;
  checks: Record<string, TunnelHealthCheck>;
}

export interface Tunnel {
  id: number;
  name: string;
  enabled: boolean;
  relay_node_id: number | null;
  intermediate_node_id?: number | null;
  intermediate_port?: number | null;
  exit_node_id: number | null;
  hops?: number;
  relay_kind: "panel" | "node";
  exit_kind: "panel" | "node";
  transport: string;
  listen_port: number;
  target_port: number;
  params?: Record<string, any> | null;
}

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  default: boolean;
  label_key: string;
  description?: string | null;
}

export interface DeploymentInfo {
  panel_region: "iran" | "foreign";
  detected_by: string;
  public_ip?: string | null;
  git_sha?: string | null;
  xray_local_version?: string | null;
}

export interface UpdateCheck {
  current_version: string;
  remote_version: string;
  current_sha?: string | null;
  remote_sha?: string | null;
  commits_behind: number;
  update_available?: boolean;
  check_source?: string;
  changelog_md: string;
  release_notes?: string;
  release_notes_i18n?: Record<string, string[]>;
  breaking?: boolean;
}

export interface UpdateStepInfo {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  detail?: string | null;
}

export interface UpdateJobInfo {
  id: string;
  status: string;
  finished: boolean;
  error_message?: string | null;
  steps: UpdateStepInfo[];
}

export interface AgentUpdateNodeInfo {
  id: number;
  name: string;
  host: string;
  eligible: boolean;
  reason?: string | null;
  core_kind?: string | null;
  region?: string | null;
  status?: string | null;
}

export interface AgentUpdateCheck {
  package_url: string;
  package_reachable: boolean;
  package_etag?: string | null;
  package_last_modified?: string | null;
  package_error?: string | null;
  mirror_url?: string | null;
  mirror_reachable: boolean;
  agent_image: string;
  nodes_total: number;
  nodes_eligible: number;
  nodes_skipped: number;
  update_available: boolean;
  nodes: AgentUpdateNodeInfo[];
  ssh_available: boolean;
  checked_at: number;
}

export interface AgentNodeJobInfo {
  node_id: number;
  node_name: string;
  host: string;
  status: string;
  message?: string | null;
  error?: string | null;
}

export interface AgentUpdateJobInfo {
  id: string;
  status: string;
  finished: boolean;
  message?: string | null;
  error_message?: string | null;
  nodes: AgentNodeJobInfo[];
}

export interface ImportPreviewRow {
  username: string;
  data_limit: number;
  expire: number;
  note: string;
  status: string;
  conflict?: string | null;
  unmapped_inbounds: string[];
  source?: string | null;
  proxies?: Record<string, unknown>;
}

export interface ImportPreviewResponse {
  rows: ImportPreviewRow[];
  total: number;
  truncated?: boolean;
  source?: string;
  format_hint?: string;
  counts?: { total: number; new: number; exists: number; invalid: number };
  panel_inbound_tags?: string[];
}

export interface Rule {
  id: number;
  name: string;
  trigger_event: string;
  action: string;
  enabled: boolean;
  condition?: Record<string, any> | null;
  action_params?: Record<string, any> | null;
  created_at: string;
}

export interface Workflow {
  id: number;
  name: string;
  trigger_event: string;
  steps: { action: string; params?: Record<string, any> }[];
  enabled: boolean;
  condition?: Record<string, any> | null;
  created_at: string;
}

export interface Plan {
  id: number;
  name: string;
  price: number;
  data_limit?: number | null;
  duration_days?: number | null;
  device_limit?: number | null;
  enabled: boolean;
  tenant_id?: number | null;
  owner_admin_id?: number | null;
}

export interface Invoice {
  id: number;
  admin_id: number;
  plan_id?: number | null;
  amount: number;
  status: string;
  provider?: string | null;
  description?: string | null;
  created_at?: string | null;
  paid_at?: string | null;
}

export interface Transaction {
  id: number;
  admin_id: number;
  amount: number;
  type: string;
  description?: string | null;
  reference?: string | null;
  created_at?: string | null;
}

export interface Wallet {
  admin_id: number;
  balance: number;
}

export interface OnboardingStatus {
  show_wizard: boolean;
  completed: boolean;
  steps: Record<string, boolean>;
}

export interface MrrSummary {
  period_days: number;
  total_revenue: number;
  mrr_estimate: number;
  by_type: Record<string, number>;
  wallet_float: number;
  active_resellers: number;
  sub_resellers: number;
  top_resellers: { admin_id: number; username: string; revenue: number }[];
}

export interface GatewayIncomeReseller {
  admin_id: number;
  username: string;
  is_sudo?: boolean;
  centralpay_enabled?: boolean;
  card_enabled?: boolean;
  today: number;
  yesterday: number;
  week: number;
  total: number;
  payments_count: number;
  by_provider: Record<string, number>;
  by_kind: Record<string, number>;
}

export interface GatewayIncomePayment {
  id: number;
  kind: string;
  provider: string;
  amount: number;
  status: string;
  admin_id: number;
  username?: string | null;
  plan_id?: number | null;
  plan_name?: string | null;
  reference?: string | number | null;
  card?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
}

export interface GatewayIncome {
  today: number;
  yesterday: number;
  week: number;
  total: number;
  today_count?: number;
  yesterday_count?: number;
  week_count?: number;
  payments_count: number;
  currency_label: string;
  by_provider: Record<string, number>;
  by_kind: Record<string, number>;
  today_by_kind?: Record<string, number>;
  yesterday_by_kind?: Record<string, number>;
  week_by_kind?: Record<string, number>;
  total_by_kind?: Record<string, number>;
  resellers: GatewayIncomeReseller[];
  recent_payments: GatewayIncomePayment[];
}

export interface SubResellerAccount {
  username: string;
  role?: string | null;
  max_users?: number | null;
  max_nodes?: number | null;
  parent_admin_id?: number | null;
  commission_percent?: number;
}

export interface UsageSummary {
  rate_per_gb: number;
  discount_percent: number;
  period_since: string;
  period_until: string;
  owned_bytes: number;
  foreign_bytes: number;
  owned_gb: number;
  foreign_gb: number;
  estimated_cost: number;
  wallet_balance: number;
  wallet_low: boolean;
  wallet_low_threshold: number;
  wallet_blocked?: boolean;
  currency_label?: string | null;
  prepaid_traffic_remaining?: number;
  package_covered_bytes?: number;
  overflow_owned_bytes?: number;
  overflow_foreign_bytes?: number;
}

export interface TrafficPackage {
  id: number;
  name: string;
  bytes: number;
  price: number;
  enabled: boolean;
  created_at?: string | null;
  catalog_price?: number | null;
  catalog_bytes?: number | null;
  overridden?: boolean | null;
  price_overridden?: boolean | null;
  bytes_overridden?: boolean | null;
}

export interface ResellerPricingPackage {
  id: number;
  name: string;
  enabled: boolean;
  catalog_price: number;
  catalog_bytes: number;
  price: number;
  bytes: number;
  price_overridden: boolean;
  bytes_overridden: boolean;
  overridden: boolean;
  created_at?: string | null;
}

export interface ResellerPricing {
  username: string;
  usage_rate_per_gb?: number | null;
  effective_usage_rate_per_gb: number;
  platform_usage_rate_per_gb: number;
  packages: ResellerPricingPackage[];
}

export interface TrafficPurchase {
  id: number;
  admin_id: number;
  package_id?: number | null;
  bytes: number;
  price_paid: number;
  source: string;
  created_by_admin_id?: number | null;
  created_at?: string | null;
  prepaid_traffic_remaining?: number | null;
}

export interface ResellerWorkspace {
  username: string;
  role: string;
  tenant_id?: number | null;
  tenant_name?: string | null;
  tenant_slug?: string | null;
  byo_node_discount_percent: number;
  users_count: number;
  max_users?: number | null;
  nodes_count: number;
  max_nodes?: number | null;
  wallet_balance?: number | null;
  wallet_low?: boolean;
  wallet_blocked?: boolean;
  usage_rate_per_gb?: number;
  users_usage: number;
  max_total_traffic?: number | null;
  traffic_remaining?: number | null;
  prepaid_traffic_remaining?: number;
  pending_usage_cost?: number;
  pending_usage_bytes?: number;
  capped_users?: number;
  currency_label?: string | null;
  last_usage_debit?: {
    id: number;
    amount: number;
    description?: string | null;
    created_at?: string | null;
  } | null;
}

export interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  scopes?: string[] | null;
  revoked: boolean;
}

export interface TopUser {
  username: string;
  used_traffic: number;
  status: string;
}

export interface RealtimeStats {
  online_users: number;
  users_active: number;
  nodes_connected: number;
  incoming_bandwidth_speed: number;
  outgoing_bandwidth_speed: number;
  bandwidth_source?: string;
  bandwidth_scope?: string;
}

export interface PluginsStatus {
  enabled: boolean;
  plugins: { name: string; description: string }[];
}
