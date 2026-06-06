import { FC, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

export const PathCard: FC<{
  icon: ReactNode;
  title: string;
  steps: string;
  action: string;
  to: string;
  tone?: "accent" | "ok" | "info";
}> = ({ icon, title, steps, action, to, tone = "accent" }) => {
  const nav = useNavigate();
  return (
    <button type="button" className={`nx-path-card nx-path-${tone}`} onClick={() => nav(to)}>
      <div className="nx-path-icon">{icon}</div>
      <div className="nx-path-title">{title}</div>
      <div className="nx-path-steps">{steps}</div>
      <div className="nx-path-action">{action} →</div>
    </button>
  );
};
