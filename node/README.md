# NexusPanel node agent

Remote Xray node that the panel controls over RPyC (default) or REST.

## Build the image (required before SSH provisioning)

On the panel server or any machine with Docker:

```bash
cd /opt/nexuspanel/node
docker build -t nexuspanel/node:latest .
```

Set in the panel `.env` (optional if you use the default tag):

```env
NODE_AGENT_IMAGE=nexuspanel/node:latest
```

## Run manually

```bash
docker run -d --name nexusnode --restart=always --network=host \
  -e SERVICE_PROTOCOL=rpyc \
  -v /var/lib/nexuspanel-node:/var/lib/nexuspanel-node \
  nexuspanel/node:latest
```

Then register the node from the panel (Settings → Nodes) or use bootstrap with `NODE_BOOTSTRAP_TOKEN`.
