# Shahkar node agent

Remote Xray node that the panel controls over RPyC (default) or REST.

## Build the image (required before SSH provisioning)

On the panel server or any machine with Docker:

```bash
cd /opt/shahkar/node
docker build -t shahkar/node:latest .
```

Set in the panel `.env` (optional if you use the default tag):

```env
NODE_AGENT_IMAGE=shahkar/node:latest
```

## Run manually

```bash
docker run -d --name shahkarnode --restart=always --network=host \
  -e SERVICE_PROTOCOL=rpyc \
  -v /var/lib/shahkar-node:/var/lib/shahkar-node \
  shahkar/node:latest
```

Then register the node from the panel (Settings → Nodes) or use bootstrap with `NODE_BOOTSTRAP_TOKEN`.
