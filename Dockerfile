ARG PYTHON_VERSION=3.12

FROM python:$PYTHON_VERSION-slim AS build

ENV PYTHONUNBUFFERED=1

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl unzip gcc python3-dev libpq-dev \
    && case "$(uname -m)" in \
         x86_64|amd64) XRAY_ARCH=64 ;; \
         aarch64|arm64) XRAY_ARCH=arm64-v8a ;; \
         armv7l) XRAY_ARCH=arm32-v7a ;; \
         *) XRAY_ARCH=64 ;; \
       esac \
    && curl -L -o /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip" \
    && unzip -o /tmp/xray.zip -d /tmp/xray \
    && install -m 0755 /tmp/xray/xray /usr/local/bin/xray \
    && mkdir -p /usr/local/share/xray \
    && mv /tmp/xray/*.dat /usr/local/share/xray/ \
    && rm -rf /tmp/xray /tmp/xray.zip \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /code/
RUN python3 -m pip install --upgrade pip setuptools \
    && pip install --no-cache-dir --upgrade -r /code/requirements.txt \
    && SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && mkdir -p /nexuspanel-export/site-packages \
    && cp -a "${SITE}/." /nexuspanel-export/site-packages/

FROM python:$PYTHON_VERSION-slim

WORKDIR /code

RUN SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && rm -rf "${SITE:?}"/* \
    && mkdir -p "${SITE}"

COPY --from=build /nexuspanel-export/site-packages/ /tmp/nexuspanel-site-packages/
RUN SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && cp -a /tmp/nexuspanel-site-packages/. "${SITE}/" \
    && rm -rf /tmp/nexuspanel-site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /usr/local/share/xray /usr/local/share/xray

# git + docker CLI + runuser for entrypoint privilege drop.
# procps provides `pgrep`, used by the Xray core health-check job
# (app/jobs/0_xray_core.py) and _kill_stale_stdin_xray() to find/reap stray
# `xray run -config stdin:` processes. Without it those checks always see
# zero matching processes and the health check restarts a perfectly healthy
# core on every tick (~every JOB_CORE_HEALTH_CHECK_INTERVAL seconds).
# docker-cli/docker-compose/docker-buildx (client-only, no dockerd/containerd)
# let the panel drive the HOST'S docker daemon through the bind-mounted
# /var/run/docker.sock for in-dashboard updates and Postgres backup/restore
# (app/system/update_jobs.py, app/backup.py) — the panel never runs its own
# daemon. Shipping the client in the image (instead of bind-mounting the
# host's /usr/bin/docker + cli-plugins, as before) removes a host-binary
# trust dependency from docker-compose.yml (see AUDIT_FINDINGS.md C5).
# postgresql-client tracks Debian's default (17 on trixie) and must match
# docker-compose.postgres.yml (postgres:17-alpine) so pg_dump/pg_restore
# archive formats stay compatible with the live server.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git docker-cli docker-compose docker-buildx util-linux procps iproute2 iptables wireguard-tools postgresql-client openssh-client sshpass \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 nexuspanel 2>/dev/null || true \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/nexuspanel nexuspanel 2>/dev/null || true

COPY . /code

RUN test -f /code/app/dashboard-next/out/dashboard/index.html \
    || (echo "ERROR: dashboard-next not built. Run: ./build_dashboard.sh" && exit 1)

RUN ln -sf /code/nexuspanel-cli.py /usr/bin/nexuspanel-cli \
    && chmod +x /usr/bin/nexuspanel-cli \
    && cp /code/docker-entrypoint.sh /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh \
    && chown -R nexuspanel:nexuspanel /code

USER root
# Prefer the bind-mounted script at /code so entrypoint fixes ship without image rebuild.
ENTRYPOINT ["/bin/bash", "-c", "exec /bin/bash /code/docker-entrypoint.sh \"${@}\"", "--"]
CMD ["panel"]
