export interface AdminInfo {
  username: string;
  is_sudo: boolean;
  role?: string | null;
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
  relay_node_id: number;
  exit_node_id: number;
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
  current_sha?: string | null;
  remote_sha?: string | null;
  commits_behind: number;
  changelog_md: string;
  breaking?: boolean;
}

export interface ImportPreviewRow {
  username: string;
  data_limit: number;
  expire: number;
  note: string;
  status: string;
  conflict?: string | null;
  unmapped_inbounds: string[];
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
