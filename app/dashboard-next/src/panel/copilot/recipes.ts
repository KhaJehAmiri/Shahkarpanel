import { api } from "../api/client";
import { CopilotIntent } from "./CopilotContext";

/** A live snapshot of the panel, used to auto-detect which steps are done. */
export interface CopilotSnapshot {
  panelConfigured: boolean;
  nodes: number;
  wgNodes: number;
  xrayNodes: number;
  tunnels: number;
  inbounds: number;
  users: number;
}

export interface CopilotStep {
  id: string;
  titleKey: string;
  bodyKey: string;
  cta?: { labelKey: string; intent?: CopilotIntent; hash?: string };
  /** When present, the step is auto-marked done if this returns true. */
  check?: (s: CopilotSnapshot) => boolean;
}

export interface CopilotRecipe {
  id: string;
  titleKey: string;
  descKey: string;
  icon: string;
  sudoOnly?: boolean;
  requiresFlag?: string;
  steps: CopilotStep[];
}

export const emptySnapshot: CopilotSnapshot = {
  panelConfigured: false, nodes: 0, wgNodes: 0, xrayNodes: 0, tunnels: 0, inbounds: 0, users: 0,
};

/** Fetch a snapshot; every call degrades gracefully (missing perms → 0). */
export async function fetchSnapshot(isSudo: boolean): Promise<CopilotSnapshot> {
  const snap: CopilotSnapshot = { ...emptySnapshot };

  const safe = async (fn: () => Promise<void>) => { try { await fn(); } catch { /* ignore */ } };

  await Promise.all([
    safe(async () => {
      const u = await api.get<{ total: number }>("/users?limit=1");
      snap.users = u?.total ?? 0;
    }),
    safe(async () => {
      const inb = await api.get<Record<string, unknown[]>>("/inbounds");
      snap.inbounds = inb ? Object.values(inb).reduce((a, v) => a + (Array.isArray(v) ? v.length : 0), 0) : 0;
    }),
    ...(isSudo ? [
      safe(async () => {
        const nodes = await api.get<{ core_kind?: string }[]>("/nodes");
        if (Array.isArray(nodes)) {
          snap.nodes = nodes.length;
          snap.wgNodes = nodes.filter((n) => n.core_kind === "wireguard").length;
          snap.xrayNodes = nodes.filter((n) => n.core_kind !== "wireguard").length;
        }
      }),
      safe(async () => {
        const s = await api.get<{ completed: boolean }>("/setup/status");
        snap.panelConfigured = !!s?.completed;
      }),
      safe(async () => {
        const tunnels = await api.get<unknown[]>("/tunnels");
        snap.tunnels = Array.isArray(tunnels) ? tunnels.length : 0;
      }),
    ] : []),
  ]);

  return snap;
}

export const RECIPES: CopilotRecipe[] = [
  {
    id: "quickstart",
    titleKey: "copilot.quickstart.title",
    descKey: "copilot.quickstart.desc",
    icon: "🚀",
    sudoOnly: true,
    steps: [
      {
        id: "configure",
        titleKey: "copilot.quickstart.s_configure",
        bodyKey: "copilot.quickstart.s_configure_b",
        cta: { labelKey: "copilot.cta.openSystem", hash: "#/system" },
        check: (s) => s.panelConfigured,
      },
      {
        id: "server",
        titleKey: "copilot.quickstart.s_server",
        bodyKey: "copilot.quickstart.s_server_b",
        cta: { labelKey: "copilot.cta.addServer", intent: "add-node-ssh", hash: "#/nodes" },
        check: (s) => s.nodes > 0,
      },
      {
        id: "inbound",
        titleKey: "copilot.quickstart.s_inbound",
        bodyKey: "copilot.quickstart.s_inbound_b",
        cta: { labelKey: "copilot.cta.openInbounds", intent: "open-inbounds", hash: "#/inbounds" },
        check: (s) => s.inbounds > 0,
      },
      {
        id: "user",
        titleKey: "copilot.quickstart.s_user",
        bodyKey: "copilot.quickstart.s_user_b",
        cta: { labelKey: "copilot.cta.createUser", intent: "create-user", hash: "#/users" },
        check: (s) => s.users > 0,
      },
      {
        id: "share",
        titleKey: "copilot.quickstart.s_share",
        bodyKey: "copilot.quickstart.s_share_b",
        cta: { labelKey: "copilot.cta.openUsers", hash: "#/users" },
      },
    ],
  },
  {
    id: "wireguard",
    titleKey: "copilot.wg.title",
    descKey: "copilot.wg.desc",
    icon: "🛡️",
    sudoOnly: true,
    steps: [
      {
        id: "wgnode",
        titleKey: "copilot.wg.s_node",
        bodyKey: "copilot.wg.s_node_b",
        cta: { labelKey: "copilot.cta.addWgServer", intent: "add-wg-node", hash: "#/nodes" },
        check: (s) => s.wgNodes > 0,
      },
      {
        id: "wguser",
        titleKey: "copilot.wg.s_user",
        bodyKey: "copilot.wg.s_user_b",
        cta: { labelKey: "copilot.cta.createWgUser", intent: "create-wg-user", hash: "#/users" },
        check: (s) => s.users > 0,
      },
      {
        id: "wgshare",
        titleKey: "copilot.wg.s_share",
        bodyKey: "copilot.wg.s_share_b",
        cta: { labelKey: "copilot.cta.openUsers", hash: "#/users" },
      },
    ],
  },
  {
    id: "tunnel",
    titleKey: "copilot.tunnel.title",
    descKey: "copilot.tunnel.desc",
    icon: "🔗",
    sudoOnly: true,
    requiresFlag: "tunneling",
    steps: [
      {
        id: "exit",
        titleKey: "copilot.tunnel.s_exit",
        bodyKey: "copilot.tunnel.s_exit_b",
        cta: { labelKey: "copilot.cta.addServer", intent: "add-node-ssh", hash: "#/nodes" },
        check: (s) => s.nodes > 0,
      },
      {
        id: "create",
        titleKey: "copilot.tunnel.s_tunnel",
        bodyKey: "copilot.tunnel.s_tunnel_b",
        cta: { labelKey: "copilot.cta.openTunnels", hash: "#/tunnels" },
        check: (s) => s.tunnels > 0,
      },
      {
        id: "apply",
        titleKey: "copilot.tunnel.s_apply",
        bodyKey: "copilot.tunnel.s_apply_b",
        cta: { labelKey: "copilot.cta.openTunnels", hash: "#/tunnels" },
      },
    ],
  },
  {
    id: "v2ray",
    titleKey: "copilot.v2ray.title",
    descKey: "copilot.v2ray.desc",
    icon: "⚡",
    sudoOnly: true,
    steps: [
      {
        id: "xnode",
        titleKey: "copilot.v2ray.s_node",
        bodyKey: "copilot.v2ray.s_node_b",
        cta: { labelKey: "copilot.cta.addServer", intent: "add-node-ssh", hash: "#/nodes" },
        check: (s) => s.xrayNodes > 0,
      },
      {
        id: "xinbound",
        titleKey: "copilot.v2ray.s_inbound",
        bodyKey: "copilot.v2ray.s_inbound_b",
        cta: { labelKey: "copilot.cta.openInbounds", intent: "open-inbounds", hash: "#/inbounds" },
        check: (s) => s.inbounds > 0,
      },
      {
        id: "xuser",
        titleKey: "copilot.v2ray.s_user",
        bodyKey: "copilot.v2ray.s_user_b",
        cta: { labelKey: "copilot.cta.createUser", intent: "create-user", hash: "#/users" },
        check: (s) => s.users > 0,
      },
      {
        id: "xshare",
        titleKey: "copilot.v2ray.s_share",
        bodyKey: "copilot.v2ray.s_share_b",
        cta: { labelKey: "copilot.cta.openUsers", hash: "#/users" },
      },
    ],
  },
  {
    id: "autoserver",
    titleKey: "copilot.auto.title",
    descKey: "copilot.auto.desc",
    icon: "🤖",
    sudoOnly: true,
    requiresFlag: "node_provisioning",
    steps: [
      {
        id: "explain",
        titleKey: "copilot.auto.s_explain",
        bodyKey: "copilot.auto.s_explain_b",
        cta: { labelKey: "copilot.cta.addServer", intent: "add-node-ssh", hash: "#/nodes" },
        check: (s) => s.nodes > 0,
      },
    ],
  },
  {
    id: "firstuser",
    titleKey: "copilot.firstuser.title",
    descKey: "copilot.firstuser.desc",
    icon: "👤",
    steps: [
      {
        id: "fuser",
        titleKey: "copilot.firstuser.s_user",
        bodyKey: "copilot.firstuser.s_user_b",
        cta: { labelKey: "copilot.cta.createUser", intent: "create-user", hash: "#/users" },
        check: (s) => s.users > 0,
      },
      {
        id: "fshare",
        titleKey: "copilot.firstuser.s_share",
        bodyKey: "copilot.firstuser.s_share_b",
        cta: { labelKey: "copilot.cta.openUsers", hash: "#/users" },
      },
    ],
  },
];

/** How many auto-checkable steps in a recipe are satisfied. */
export function recipeProgress(recipe: CopilotRecipe, snap: CopilotSnapshot): { done: number; total: number } {
  const checkable = recipe.steps.filter((s) => s.check);
  const done = checkable.filter((s) => s.check!(snap)).length;
  return { done, total: checkable.length || recipe.steps.length };
}
