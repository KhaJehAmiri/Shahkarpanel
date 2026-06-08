import "../subscribe/subscribe.css";
import "./portal.css";

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <div className="sub-theme portal-theme">{children}</div>;
}
