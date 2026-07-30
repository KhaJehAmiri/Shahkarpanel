import { FC, ReactNode, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "./Shell";
import { SectionRail, type RailGroup } from "./SectionRail";

/** Page shell with grouped side rail — same pattern as Billing / Resellers. */
export const RailHubLayout: FC<{
  title: string;
  subtitle?: string;
  description?: string;
  groups: RailGroup[];
  defaultTab: string;
  param?: string;
  actions?: ReactNode;
  children: (tab: string) => ReactNode;
}> = ({
  title,
  subtitle,
  description,
  groups,
  defaultTab,
  param = "tab",
  actions,
  children,
}) => {
  const [search, setSearch] = useSearchParams();
  const visibleGroups = useMemo(
    () => groups.map((g) => ({ ...g, items: g.items.filter(Boolean) })).filter((g) => g.items.length > 0),
    [groups],
  );
  const allIds = useMemo(() => visibleGroups.flatMap((g) => g.items.map((i) => i.id)), [visibleGroups]);
  const fallback = allIds.includes(defaultTab) ? defaultTab : (allIds[0] || defaultTab);
  const fromUrl = search.get(param);
  const active = fromUrl && allIds.includes(fromUrl) ? fromUrl : fallback;

  const onTab = (id: string) => {
    const next = new URLSearchParams(search);
    next.set(param, id);
    setSearch(next, { replace: true });
  };

  const showRail = allIds.length > 1;

  return (
    <div className="sk-page sk-biz">
      <PageHeader title={title} subtitle={subtitle} description={description} actions={actions} />
      <div className={`sk-biz-layout${showRail ? "" : " sk-biz-layout--solo"}`}>
        {showRail && (
          <SectionRail groups={visibleGroups} active={active} onChange={onTab} label={title} />
        )}
        <div className="sk-section-panel">{children(active)}</div>
      </div>
    </div>
  );
};
