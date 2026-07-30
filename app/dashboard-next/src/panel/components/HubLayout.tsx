import { FC, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "./Shell";
import { Tabs } from "./ui";

export type HubTab = { id: string; label: string; hidden?: boolean };

export const HubLayout: FC<{
  title: string;
  subtitle?: string;
  description?: string;
  tabs: HubTab[];
  defaultTab: string;
  param?: string;
  actions?: ReactNode;
  children: (tab: string) => ReactNode;
}> = ({ title, subtitle, description, tabs, defaultTab, param = "tab", actions, children }) => {
  const [search, setSearch] = useSearchParams();
  const visible = tabs.filter((t) => !t.hidden);
  const active = visible.some((t) => t.id === search.get(param))
    ? (search.get(param) as string)
    : defaultTab;

  const onTab = (id: string) => {
    const next = new URLSearchParams(search);
    next.set(param, id);
    setSearch(next, { replace: true });
  };

  return (
    <div className="sk-hub sk-page">
      <PageHeader title={title} subtitle={subtitle} description={description} actions={actions} />
      <div className="sk-hub-tabs">
        <Tabs active={active} onChange={onTab} tabs={visible.map((t) => ({ id: t.id, label: t.label }))} />
      </div>
      <div className="sk-hub-body">{children(active)}</div>
    </div>
  );
};
