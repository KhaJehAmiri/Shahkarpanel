import { FC } from "react";

export type RailItem = { id: string; label: string; badge?: number };
export type RailGroup = { id: string; label: string; items: RailItem[] };

/** Grouped in-page navigation for Billing / Resellers hubs. */
export const SectionRail: FC<{
  groups: RailGroup[];
  active: string;
  onChange: (id: string) => void;
  label?: string;
}> = ({ groups, active, onChange, label }) => (
  <nav className="sk-rail" aria-label={label || "Sections"}>
    {groups.map((g) => (
      <div key={g.id} className="sk-rail-group">
        <div className="sk-rail-group-label">{g.label}</div>
        <div className="sk-rail-items">
          {g.items.map((item) => {
            const badge = typeof item.badge === "number" && item.badge > 0 ? item.badge : 0;
            return (
              <button
                key={item.id}
                type="button"
                className={`sk-rail-item ${active === item.id ? "active" : ""}`}
                onClick={() => onChange(item.id)}
              >
                <span className="sk-rail-item-label">{item.label}</span>
                {badge > 0 ? (
                  <span className="sk-rail-badge" aria-label={String(badge)}>
                    {badge > 99 ? "99+" : badge}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    ))}
  </nav>
);
