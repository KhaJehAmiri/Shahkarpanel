import {
  Badge,
  Box,
  Button,
  Code,
  Divider,
  FormControl,
  FormLabel,
  Grid,
  Heading,
  HStack,
  IconButton,
  Input,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tab,
  Table,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tbody,
  Td,
  Text,
  Textarea,
  Th,
  Thead,
  Tr,
  useToast,
} from "@chakra-ui/react";
import { TrashIcon } from "@heroicons/react/24/outline";
import { Shell } from "components/Shell";
import { FC, useEffect, useState } from "react";
import { fetch } from "../service/http";

const Panel: FC<{ title: string; description?: string; children: React.ReactNode }> = ({
  title,
  description,
  children,
}) => (
  <Box
    borderWidth="1px"
    borderColor="whiteAlpha.100"
    borderRadius="xl"
    p={6}
    bg={{ _dark: "gray.850", _light: "white" }}
  >
    <Stack spacing={1} mb={4}>
      <Heading size="md">{title}</Heading>
      {description && (
        <Text fontSize="sm" color="gray.500">
          {description}
        </Text>
      )}
    </Stack>
    {children}
  </Box>
);

// --------------------------------------------------------------------------- //
// Setup wizard
// --------------------------------------------------------------------------- //
const SetupTab: FC = () => {
  const toast = useToast();
  const [form, setForm] = useState<any>({
    panel_title: "",
    primary_color: "#5b8cff",
    support_url: "",
    logo_url: "",
  });
  const [features, setFeatures] = useState<Record<string, boolean>>({
    tenants: true,
    white_label: true,
    node_provisioning: true,
    tunneling: true,
    billing: false,
    smart_routing: false,
  });
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    fetch("/setup/status").then(setStatus).catch(() => {});
  }, []);

  const submit = () => {
    const enable_features = Object.entries(features)
      .filter(([, v]) => v)
      .map(([k]) => k);
    fetch("/setup/", { method: "POST", body: { ...form, enable_features } })
      .then((r) => {
        setStatus(r);
        toast({ title: "Setup completed", status: "success" });
      })
      .catch((e) =>
        toast({ title: "Setup failed", description: String(e?.data?.detail || e), status: "error" })
      );
  };

  return (
    <Panel
      title="Setup wizard"
      description="Finish first-run configuration: brand defaults and which features to enable."
    >
      {status?.completed && (
        <Badge colorScheme="green" mb={4}>
          Setup already completed — changes here are optional
        </Badge>
      )}
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        <FormControl>
          <FormLabel fontSize="sm">Panel title</FormLabel>
          <Input
            size="sm"
            value={form.panel_title}
            onChange={(e) => setForm({ ...form, panel_title: e.target.value })}
            placeholder="NexusPanel"
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">Primary color</FormLabel>
          <Input
            size="sm"
            value={form.primary_color}
            onChange={(e) => setForm({ ...form, primary_color: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">Support URL</FormLabel>
          <Input
            size="sm"
            value={form.support_url}
            onChange={(e) => setForm({ ...form, support_url: e.target.value })}
            placeholder="https://t.me/yourbrand"
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">Logo URL</FormLabel>
          <Input
            size="sm"
            value={form.logo_url}
            onChange={(e) => setForm({ ...form, logo_url: e.target.value })}
          />
        </FormControl>
      </SimpleGrid>
      <Divider my={5} />
      <Text fontSize="sm" fontWeight="semibold" mb={3}>
        Enable features
      </Text>
      <SimpleGrid columns={{ base: 2, md: 3 }} spacing={3}>
        {Object.keys(features).map((f) => (
          <HStack key={f} justify="space-between">
            <Text fontSize="sm">{f}</Text>
            <Switch
              isChecked={features[f]}
              onChange={(e) => setFeatures({ ...features, [f]: e.target.checked })}
            />
          </HStack>
        ))}
      </SimpleGrid>
      <Button mt={6} colorScheme="blue" onClick={submit}>
        Apply setup
      </Button>
    </Panel>
  );
};

// --------------------------------------------------------------------------- //
// Branding
// --------------------------------------------------------------------------- //
const BrandingTab: FC = () => {
  const toast = useToast();
  const [b, setB] = useState<any>({});

  useEffect(() => {
    fetch("/branding/mine").then(setB).catch(() => {});
  }, []);

  const save = () => {
    fetch("/branding/mine", { method: "PUT", body: b })
      .then((r) => {
        setB(r);
        toast({ title: "Branding saved", status: "success" });
      })
      .catch((e) =>
        toast({ title: "Save failed", description: String(e?.data?.detail || e), status: "error" })
      );
  };

  const field = (key: string, label: string, ph = "") => (
    <FormControl>
      <FormLabel fontSize="sm">{label}</FormLabel>
      <Input
        size="sm"
        value={b[key] || ""}
        placeholder={ph}
        onChange={(e) => setB({ ...b, [key]: e.target.value })}
      />
    </FormControl>
  );

  return (
    <Panel
      title="White-label branding"
      description="Resellers edit their own brand here; the owner edits the global default."
    >
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        {field("panel_title", "Panel title")}
        {field("primary_color", "Primary color", "#5b8cff")}
        {field("logo_url", "Logo URL")}
        {field("favicon_url", "Favicon URL")}
        {field("support_url", "Support URL")}
        {field("sub_profile_title", "Subscription profile title")}
        {field("domain", "Custom domain")}
      </SimpleGrid>
      <Button mt={6} colorScheme="blue" onClick={save}>
        Save branding
      </Button>
    </Panel>
  );
};

// --------------------------------------------------------------------------- //
// Provision reseller node over SSH
// --------------------------------------------------------------------------- //
const ProvisionTab: FC = () => {
  const toast = useToast();
  const [form, setForm] = useState<any>({
    name: "",
    host: "",
    ssh_port: 22,
    username: "root",
    password: "",
    role: "direct",
    run: true,
  });
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const provision = () => {
    setBusy(true);
    setResult(null);
    fetch("/nodes/provision", { method: "POST", body: form })
      .then((r) => {
        setResult(r);
        toast({
          title: r.status === "provisioned" ? "Provisioned" : "Manual install required",
          status: r.status === "provisioned" ? "success" : "info",
        });
      })
      .catch((e) =>
        toast({ title: "Failed", description: String(e?.data?.detail || e), status: "error" })
      )
      .finally(() => setBusy(false));
  };

  return (
    <Panel
      title="Add your own node (SSH)"
      description="Enter your server IP and SSH password — the panel installs the node agent and it self-registers under your tenant."
    >
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        <FormControl isRequired>
          <FormLabel fontSize="sm">Node name</FormLabel>
          <Input size="sm" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </FormControl>
        <FormControl isRequired>
          <FormLabel fontSize="sm">Server IP / host</FormLabel>
          <Input size="sm" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">SSH port</FormLabel>
          <Input
            size="sm"
            type="number"
            value={form.ssh_port}
            onChange={(e) => setForm({ ...form, ssh_port: Number(e.target.value) })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">SSH username</FormLabel>
          <Input
            size="sm"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">SSH password</FormLabel>
          <Input
            size="sm"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="sm">Topology role</FormLabel>
          <Select size="sm" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="direct">direct</option>
            <option value="relay">relay (in-country bridge)</option>
            <option value="exit">exit (foreign exit)</option>
          </Select>
        </FormControl>
      </SimpleGrid>
      <HStack mt={4} spacing={4}>
        <Switch
          isChecked={form.run}
          onChange={(e) => setForm({ ...form, run: e.target.checked })}
        />
        <Text fontSize="sm">Run install over SSH now (uncheck to just get the command)</Text>
      </HStack>
      <Button mt={5} colorScheme="blue" isLoading={busy} onClick={provision}>
        Provision node
      </Button>

      {result && (
        <Box mt={5}>
          <Text fontSize="sm" fontWeight="semibold" mb={2}>
            {result.detail}
          </Text>
          <Text fontSize="xs" color="gray.500" mb={1}>
            Install command (run on your server as root):
          </Text>
          <Code
            display="block"
            whiteSpace="pre-wrap"
            p={3}
            borderRadius="md"
            fontSize="xs"
            overflowX="auto"
          >
            {result.install_command}
          </Code>
        </Box>
      )}
    </Panel>
  );
};

// --------------------------------------------------------------------------- //
// Tunnels
// --------------------------------------------------------------------------- //
const TunnelsTab: FC = () => {
  const toast = useToast();
  const [tunnels, setTunnels] = useState<any[]>([]);
  const [nodes, setNodes] = useState<any[]>([]);
  const [form, setForm] = useState<any>({
    name: "",
    relay_node_id: "",
    exit_node_id: "",
    transport: "reality",
    listen_port: 443,
    target_port: 8443,
  });

  const load = () => {
    fetch("/tunnels").then(setTunnels).catch(() => {});
    fetch("/nodes").then(setNodes).catch(() => {});
  };
  useEffect(load, []);

  const create = () => {
    fetch("/tunnels", {
      method: "POST",
      body: {
        ...form,
        relay_node_id: Number(form.relay_node_id),
        exit_node_id: Number(form.exit_node_id),
        listen_port: Number(form.listen_port),
        target_port: Number(form.target_port),
      },
    })
      .then(() => {
        toast({ title: "Tunnel created", status: "success" });
        load();
      })
      .catch((e) =>
        toast({ title: "Failed", description: String(e?.data?.detail || e), status: "error" })
      );
  };

  const remove = (id: number) => {
    fetch(`/tunnels/${id}`, { method: "DELETE" }).then(load);
  };

  return (
    <Panel
      title="Iran ↔ foreign tunnels"
      description="Bridge an in-country relay node to a foreign exit node over an encrypted hop."
    >
      <Grid templateColumns={{ base: "1fr", md: "repeat(6, 1fr)" }} gap={3} alignItems="end">
        <FormControl>
          <FormLabel fontSize="xs">Name</FormLabel>
          <Input size="sm" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Relay node</FormLabel>
          <Select
            size="sm"
            value={form.relay_node_id}
            onChange={(e) => setForm({ ...form, relay_node_id: e.target.value })}
          >
            <option value="">—</option>
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name}
              </option>
            ))}
          </Select>
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Exit node</FormLabel>
          <Select
            size="sm"
            value={form.exit_node_id}
            onChange={(e) => setForm({ ...form, exit_node_id: e.target.value })}
          >
            <option value="">—</option>
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name}
              </option>
            ))}
          </Select>
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Transport</FormLabel>
          <Select
            size="sm"
            value={form.transport}
            onChange={(e) => setForm({ ...form, transport: e.target.value })}
          >
            <option value="reality">reality</option>
            <option value="ws">ws</option>
            <option value="grpc">grpc</option>
            <option value="tcp">tcp</option>
          </Select>
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Listen port</FormLabel>
          <Input
            size="sm"
            type="number"
            value={form.listen_port}
            onChange={(e) => setForm({ ...form, listen_port: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Target port</FormLabel>
          <Input
            size="sm"
            type="number"
            value={form.target_port}
            onChange={(e) => setForm({ ...form, target_port: e.target.value })}
          />
        </FormControl>
      </Grid>
      <Button mt={4} size="sm" colorScheme="blue" onClick={create}>
        Create tunnel
      </Button>

      <Table mt={6} size="sm" variant="simple">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Relay → Exit</Th>
            <Th>Transport</Th>
            <Th>Ports</Th>
            <Th></Th>
          </Tr>
        </Thead>
        <Tbody>
          {tunnels.map((t) => (
            <Tr key={t.id}>
              <Td>{t.name}</Td>
              <Td>
                {t.relay_node_id} → {t.exit_node_id}
              </Td>
              <Td>{t.transport}</Td>
              <Td>
                {t.listen_port} / {t.target_port}
              </Td>
              <Td>
                <IconButton
                  aria-label="delete"
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  icon={<TrashIcon width={16} />}
                  onClick={() => remove(t.id)}
                />
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Panel>
  );
};

// --------------------------------------------------------------------------- //
// Tenants
// --------------------------------------------------------------------------- //
const TenantsTab: FC = () => {
  const toast = useToast();
  const [tenants, setTenants] = useState<any[]>([]);
  const [form, setForm] = useState<any>({
    name: "",
    owner_username: "",
    byo_node_discount_percent: 0,
    max_users: "",
    max_nodes: "",
  });

  const load = () => fetch("/tenants").then(setTenants).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const create = () => {
    const body: any = {
      name: form.name,
      byo_node_discount_percent: Number(form.byo_node_discount_percent) || 0,
    };
    if (form.owner_username) body.owner_username = form.owner_username;
    if (form.max_users) body.max_users = Number(form.max_users);
    if (form.max_nodes) body.max_nodes = Number(form.max_nodes);
    fetch("/tenants", { method: "POST", body })
      .then(() => {
        toast({ title: "Tenant created", status: "success" });
        load();
      })
      .catch((e) =>
        toast({ title: "Failed", description: String(e?.data?.detail || e), status: "error" })
      );
  };

  const remove = (id: number) => {
    fetch(`/tenants/${id}`, { method: "DELETE" }).then(load);
  };

  return (
    <Panel
      title="Reseller tenants"
      description="Each tenant is a white-label reseller workspace inside this single install."
    >
      <Grid templateColumns={{ base: "1fr", md: "repeat(5, 1fr)" }} gap={3} alignItems="end">
        <FormControl>
          <FormLabel fontSize="xs">Name</FormLabel>
          <Input size="sm" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Owner admin (username)</FormLabel>
          <Input
            size="sm"
            value={form.owner_username}
            onChange={(e) => setForm({ ...form, owner_username: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">BYO discount %</FormLabel>
          <Input
            size="sm"
            type="number"
            value={form.byo_node_discount_percent}
            onChange={(e) => setForm({ ...form, byo_node_discount_percent: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Max users</FormLabel>
          <Input
            size="sm"
            type="number"
            value={form.max_users}
            onChange={(e) => setForm({ ...form, max_users: e.target.value })}
          />
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs">Max nodes</FormLabel>
          <Input
            size="sm"
            type="number"
            value={form.max_nodes}
            onChange={(e) => setForm({ ...form, max_nodes: e.target.value })}
          />
        </FormControl>
      </Grid>
      <Button mt={4} size="sm" colorScheme="blue" onClick={create}>
        Create tenant
      </Button>

      <Table mt={6} size="sm" variant="simple">
        <Thead>
          <Tr>
            <Th>Slug</Th>
            <Th>Name</Th>
            <Th>BYO discount</Th>
            <Th>Limits</Th>
            <Th>Enabled</Th>
            <Th></Th>
          </Tr>
        </Thead>
        <Tbody>
          {tenants.map((t) => (
            <Tr key={t.id}>
              <Td>
                <Code fontSize="xs">{t.slug}</Code>
              </Td>
              <Td>{t.name}</Td>
              <Td>{t.byo_node_discount_percent}%</Td>
              <Td>
                {t.max_users ?? "∞"} users / {t.max_nodes ?? "∞"} nodes
              </Td>
              <Td>{t.enabled ? "✓" : "✗"}</Td>
              <Td>
                <IconButton
                  aria-label="delete"
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  icon={<TrashIcon width={16} />}
                  onClick={() => remove(t.id)}
                />
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Panel>
  );
};

export const Manage: FC = () => {
  return (
    <Shell title="White-label & infrastructure">
      <Tabs colorScheme="blue" variant="soft-rounded" isLazy>
        <TabList flexWrap="wrap" gap={2} mb={4}>
          <Tab fontSize="sm">Setup</Tab>
          <Tab fontSize="sm">Branding</Tab>
          <Tab fontSize="sm">Reseller nodes</Tab>
          <Tab fontSize="sm">Tunnels</Tab>
          <Tab fontSize="sm">Tenants</Tab>
        </TabList>
        <TabPanels>
          <TabPanel px={0}>
            <SetupTab />
          </TabPanel>
          <TabPanel px={0}>
            <BrandingTab />
          </TabPanel>
          <TabPanel px={0}>
            <ProvisionTab />
          </TabPanel>
          <TabPanel px={0}>
            <TunnelsTab />
          </TabPanel>
          <TabPanel px={0}>
            <TenantsTab />
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Shell>
  );
};

export default Manage;
