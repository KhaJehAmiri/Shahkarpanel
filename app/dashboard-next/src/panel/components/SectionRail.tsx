import { FC } from "react";

export type RailItem = { id: string; label: string };
export type RailGroup = { id: string; label: string; items: RailItem[] };

/** Grouped in-page navigation for Billing / Resellers hubs. */
export const SectionRail: FC<{
  groups: RailGroup[];
  active: string;
  onChange: (id: string) => void;
  label?: string;
}> = ({ groups, active, onChange, label }) => (
  <nav className="nx-rail" aria-label={label || "Sections"}>
    {groups.map((g) => (
      <div key={g.id} className="nx-rail-group">
        <div className="nx-rail-group-label">{g.label}</div>
        <div className="nx-rail-items">
          {g.items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nx-rail-item ${active === item.id ? "active" : ""}`}
              onClick={() => onChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    ))}
  </nav>
);
