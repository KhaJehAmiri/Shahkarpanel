import { CSSProperties, FC } from "react";

type P = { className?: string; size?: number; style?: CSSProperties };
const S: FC<P & { children: any }> = ({ className, size = 18, style, children }) => (
  <svg
    className={className}
    style={style}
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.8}
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {children}
  </svg>
);

export const IcDashboard: FC<P> = (p) => (
  <S {...p}><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></S>
);
export const IcUsers: FC<P> = (p) => (
  <S {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></S>
);
export const IcServer: FC<P> = (p) => (
  <S {...p}><rect x="2" y="3" width="20" height="7" rx="2" /><rect x="2" y="14" width="20" height="7" rx="2" /><path d="M6 6.5h.01M6 17.5h.01" /></S>
);
export const IcInbound: FC<P> = (p) => (
  <S {...p}><path d="M12 3v6M8.5 6.5 12 3l3.5 3.5" /><rect x="3" y="11" width="18" height="10" rx="2" /><path d="M8 15h8M8 18h5" /></S>
);
export const IcStore: FC<P> = (p) => (
  <S {...p}><path d="M3 9l1-5h16l1 5" /><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9" /><path d="M9 20v-6h6v6" /></S>
);
export const IcBolt: FC<P> = (p) => (
  <S {...p}><path d="M13 2L4.5 13.5H11l-1 8.5L19.5 10H13z" /></S>
);
export const IcChart: FC<P> = (p) => (
  <S {...p}><path d="M3 3v18h18" /><path d="M7 14l3-3 3 3 4-5" /></S>
);
export const IcWallet: FC<P> = (p) => (
  <S {...p}><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M16 12h.01" /><path d="M21 9h-5a3 3 0 0 0 0 6h5" /></S>
);
export const IcCog: FC<P> = (p) => (
  <S {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.82 1.17V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 7.27 19a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 3 13.27 1.65 1.65 0 0 0 1.83 12H1a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 3 6.27a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8 1.83 1.65 1.65 0 0 0 9.18 1H12a2 2 0 0 1 0 4h-.09" /></S>
);
export const IcMenu: FC<P> = (p) => (<S {...p}><path d="M3 6h18M3 12h18M3 18h18" /></S>);
export const IcSun: FC<P> = (p) => (<S {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></S>);
export const IcMoon: FC<P> = (p) => (<S {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></S>);
export const IcLogout: FC<P> = (p) => (<S {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></S>);
export const IcPlus: FC<P> = (p) => (<S {...p}><path d="M12 5v14M5 12h14" /></S>);
export const IcTrash: FC<P> = (p) => (<S {...p}><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></S>);
export const IcClose: FC<P> = (p) => (<S {...p}><path d="M18 6L6 18M6 6l12 12" /></S>);
export const IcCheck: FC<P> = (p) => (<S {...p}><path d="M20 6L9 17l-5-5" /></S>);
export const IcRefresh: FC<P> = (p) => (<S {...p}><path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /></S>);
export const IcGlobe: FC<P> = (p) => (<S {...p}><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z" /></S>);
export const IcLink: FC<P> = (p) => (<S {...p}><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5" /></S>);
export const IcShield: FC<P> = (p) => (<S {...p}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></S>);
export const IcKey: FC<P> = (p) => (<S {...p}><circle cx="7.5" cy="15.5" r="4.5" /><path d="M10.7 12.3L21 2M16 7l3 3M14 9l2 2" /></S>);
export const IcBrush: FC<P> = (p) => (<S {...p}><path d="M9.06 11.9l8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08" /><path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z" /></S>);
export const IcDownload: FC<P> = (p) => (<S {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></S>);
export const IcAlert: FC<P> = (p) => (<S {...p}><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></S>);
export const IcFlag: FC<P> = (p) => (<S {...p}><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><path d="M4 22v-7" /></S>);
export const IcShare: FC<P> = (p) => (<S {...p}><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="M8.6 13.5L15.4 17.5M15.4 6.5L8.6 10.5" /></S>);
export const IcSearch: FC<P> = (p) => (<S {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></S>);
export const IcEdit: FC<P> = (p) => (<S {...p}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.4 2.6a2 2 0 0 1 2.8 2.8L12 14.6 8 16l1.4-4z" /></S>);
export const IcEye: FC<P> = (p) => (<S {...p}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></S>);
export const IcExternal: FC<P> = (p) => (<S {...p}><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6" /><path d="M10 14L21 3" /></S>);
export const IcCopy: FC<P> = (p) => (<S {...p}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></S>);
export const IcMonitor: FC<P> = (p) => (<S {...p}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></S>);

export const navIcon = (key: string, cls = "nx-ico"): any => {
  const m: Record<string, FC<P>> = {
    home: IcDashboard,
    overview: IcDashboard,
    users: IcUsers,
    servers: IcServer,
    connection: IcInbound,
    business: IcWallet,
    system: IcCog,
    // legacy / hub tabs
    inbounds: IcInbound,
    nodes: IcServer,
    tunnels: IcLink,
    wireguard: IcShield,
    singbox: IcBolt,
    dedip: IcGlobe,
    xray: IcBolt,
    hosts: IcGlobe,
    resellers: IcStore,
    automation: IcBolt,
    analytics: IcChart,
    billing: IcWallet,
    infra: IcServer,
    infrastructure: IcServer,
  };
  const C = m[key] || IcDashboard;
  return <C className={cls} />;
};
