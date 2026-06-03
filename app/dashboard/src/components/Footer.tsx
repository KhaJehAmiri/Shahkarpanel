import { Text } from "@chakra-ui/react";
import { useDashboard } from "contexts/DashboardContext";
import { FC } from "react";

/** Minimal footer — main chrome lives in Shell sidebar. */
export const Footer: FC = () => {
  const { version } = useDashboard();
  return (
    <Text display="none" aria-hidden>
      NexusPanel {version ? `v${version}` : ""}
    </Text>
  );
};
