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
    <button type="button" className={`sk-path-card sk-path-${tone}`} onClick={() => nav(to)}>
      <div className="sk-path-icon">{icon}</div>
      <div className="sk-path-title">{title}</div>
      <div className="sk-path-steps">{steps}</div>
      <div className="sk-path-action">{action} →</div>
    </button>
  );
};
