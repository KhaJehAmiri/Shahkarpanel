ARG PYTHON_VERSION=3.12
ARG INCLUDE_AWG=0

FROM python:$PYTHON_VERSION-slim AS build

ARG INCLUDE_AWG=0
ENV PYTHONUNBUFFERED=1
WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl unzip gcc python3-dev \
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
    && case "$(uname -m)" in \
         x86_64|amd64) SB_ARCH=amd64 ;; \
         aarch64|arm64) SB_ARCH=arm64 ;; \
         *) SB_ARCH=amd64 ;; \
       esac \
    && SB_VER="$(curl -fsSL https://api.github.com/repos/SagerNet/sing-box/releases/latest | grep -oE '\"tag_name\": \"v[^\"]+' | head -n1 | cut -d'v' -f2)" \
    && SB_VER="${SB_VER:-1.10.7}" \
    && curl -fsSL -o /tmp/sing-box.tgz "https://github.com/SagerNet/sing-box/releases/download/v${SB_VER}/sing-box-${SB_VER}-linux-${SB_ARCH}.tar.gz" \
    && tar -xzf /tmp/sing-box.tgz -C /tmp \
    && install -m 0755 "/tmp/sing-box-${SB_VER}-linux-${SB_ARCH}/sing-box" /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box.tgz "/tmp/sing-box-${SB_VER}-linux-${SB_ARCH}" \
    && rm -rf /var/lib/apt/lists/*

# Panel-bundled AmneziaWG binaries (no git clone on the remote node).
COPY prebuilt/ /tmp/prebuilt/
RUN set -eux; \
    ARCH=$(case "$(uname -m)" in x86_64|amd64) echo amd64 ;; aarch64|arm64) echo arm64 ;; *) echo amd64 ;; esac); \
    PB="/tmp/prebuilt/linux-${ARCH}"; \
    if [ -f "${PB}/sing-box" ]; then \
      install -m 0755 "${PB}/sing-box" /usr/local/bin/sing-box; \
    fi; \
    if [ "$INCLUDE_AWG" = "1" ]; then \
      ARCH=$(case "$(uname -m)" in x86_64|amd64) echo amd64 ;; aarch64|arm64) echo arm64 ;; *) echo amd64 ;; esac); \
      PB="/tmp/prebuilt/linux-${ARCH}"; \
      test -f "${PB}/amneziawg-go" && test -f "${PB}/awg"; \
      install -m 0755 "${PB}/amneziawg-go" /usr/local/bin/amneziawg-go; \
      install -m 0755 "${PB}/awg" /usr/local/bin/awg; \
    fi

COPY requirements.txt /code/
RUN python3 -m pip install --upgrade pip setuptools \
    && pip install --no-cache-dir --upgrade -r /code/requirements.txt \
    && SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && mkdir -p /shahkar-export/site-packages \
    && cp -a "${SITE}/." /shahkar-export/site-packages/

FROM python:$PYTHON_VERSION-slim

WORKDIR /code

# wireguard-tools (`wg`) + iproute2 (`ip`) are required for the WireGuard
# product protocol (Phase 11). The container must also run with the NET_ADMIN
# capability to create/manage the interface (see docker-compose / install docs).
RUN apt-get update \
    && apt-get install -y --no-install-recommends wireguard-tools iproute2 procps iptables \
    && rm -rf /var/lib/apt/lists/*

RUN SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && rm -rf "${SITE:?}"/* \
    && mkdir -p /var/lib/shahkar-node "${SITE}"

COPY --from=build /shahkar-export/site-packages/ /tmp/shahkar-site-packages/
RUN SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && cp -a /tmp/shahkar-site-packages/. "${SITE}/" \
    && rm -rf /tmp/shahkar-site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /usr/local/share/xray /usr/local/share/xray
COPY . /code

ENV SERVICE_PROTOCOL=rpyc
VOLUME ["/var/lib/shahkar-node"]

CMD ["bash", "-c", "python main.py"]
