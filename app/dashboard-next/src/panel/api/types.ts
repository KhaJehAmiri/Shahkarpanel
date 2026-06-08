export interface AdminInfo {
  username: string;
  is_sudo: boolean;
  role?: string | null;
  max_users?: number | null;
  max_nodes?: number | null;
  tenant_id?: number | null;
  telegram_id?: number | null;
  discord_webhook?: string | null;
}

export interface SystemStats {
  version: string;
  mem_total: number;
  mem_used: number;
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
}

export interface UserItem {
  username: string;
  status: string;
  used_traffic: number;
  data_limit: number | null;
  expire: number | null;
  online_at: string | null;
  data_limit_reset_strategy?: string;
  note?: string;
  admin?: { username: string } | null;
  proxies?: Record<string, any>;
  inbounds?: Record<string, string[]>;
  links?: string[];
  subscription_url?: string;
  public_subscription_url?: string;
  portal_enabled?: boolean;
  client_profile?: string | null;
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

export interface AmneziaWGParams {
  awg_jc?: number | null;
  awg_jmin?: number | null;
  awg_jmax?: number | null;
  awg_s1?: number | null;
  awg_s2?: number | null;
  awg_h1?: number | null;
  awg_h2?: number | null;
  awg_h3?: number | null;
  awg_h4?: number | null;
}

export interface InboundInfo {
  tag: string;
  protocol: string;
  network: string;
  tls: string;
  port: number | string;
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
  capacity?: number | null;
  latency_ms?: number | null;
  core_kind?: string;
  provision_status?: string | null;
  provision_message?: string | null;
  provision_progress?: number | null;
  provision_step?: string | null;
  wireguard?: ({
    public_key?: string | null;
    endpoint?: string | null;
    listen_port?: number;
  } & AmneziaWGParams) | null;
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
}

export interface Tunnel {
  id: number;
  name: string;
  enabled: boolean;
  relay_node_id: number | null;
  exit_node_id: number | null;
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
  changelog_md: string;
  release_notes?: string;
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
}

export interface Transaction {
  id: number;
  admin_id: number;
  amount: number;
  type: string;
  description?: string | null;
  reference?: string | null;
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
  usage_rate_per_gb?: number;
  users_usage: number;
  max_total_traffic?: number | null;
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
