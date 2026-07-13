# Pre-built node binaries (bundled via agent-bundle)

Remote SSH provision often runs on servers that cannot reach GitHub. The panel
ships these binaries inside the agent tarball so `docker build` on the node never
needs `git clone`.

Layout: `linux-<arch>/amneziawg-go`, `linux-<arch>/awg`

Rebuild on the panel host (amd64 example):

```bash
./scripts/build-node-prebuilt.sh amd64
```
