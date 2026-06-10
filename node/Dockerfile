ARG PYTHON_VERSION=3.12

FROM python:$PYTHON_VERSION-slim AS build

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
    # sing-box: the node's second engine for QUIC protocols (Hysteria2/TUIC).
    && case "$(uname -m)" in \
         x86_64|amd64) SB_ARCH=amd64 ;; \
         aarch64|arm64) SB_ARCH=arm64 ;; \
         armv7l) SB_ARCH=armv7 ;; \
         *) SB_ARCH=amd64 ;; \
       esac \
    && SB_VER="$(curl -sL https://api.github.com/repos/SagerNet/sing-box/releases/latest | grep -oE '\"tag_name\": \"v[^\"]+' | head -n1 | cut -d'v' -f2)" \
    && SB_VER="${SB_VER:-1.10.7}" \
    && curl -L -o /tmp/sb.tar.gz "https://github.com/SagerNet/sing-box/releases/download/v${SB_VER}/sing-box-${SB_VER}-linux-${SB_ARCH}.tar.gz" \
    && tar -xzf /tmp/sb.tar.gz -C /tmp \
    && install -m 0755 /tmp/sing-box-${SB_VER}-linux-${SB_ARCH}/sing-box /usr/local/bin/sing-box \
    && rm -rf /tmp/sb.tar.gz /tmp/sing-box-* \
    # AmneziaWG: build userspace engine from source (no published release tarballs).
    && apt-get install -y --no-install-recommends golang-go git \
    && git clone --depth 1 https://github.com/amnezia-vpn/amneziawg-go.git /tmp/amneziawg-go \
    && cd /tmp/amneziawg-go && CGO_ENABLED=0 go build -o /usr/local/bin/amneziawg-go \
    && curl -fsSL -o /tmp/awgtools.zip "https://github.com/amnezia-vpn/amneziawg-tools/releases/download/v1.0.20260223/ubuntu-22.04-amneziawg-tools.zip" \
    && unzip -o /tmp/awgtools.zip -d /tmp/awgtools \
    && install -m 0755 /tmp/awgtools/ubuntu-22.04-amneziawg-tools/awg /usr/local/bin/awg \
    && rm -rf /tmp/amneziawg-go /tmp/awgtools /tmp/awgtools.zip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/
RUN python3 -m pip install --upgrade pip setuptools \
    && pip install --no-cache-dir --upgrade -r /code/requirements.txt \
    && SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && mkdir -p /nexuspanel-export/site-packages \
    && cp -a "${SITE}/." /nexuspanel-export/site-packages/

FROM python:$PYTHON_VERSION-slim

WORKDIR /code

# wireguard-tools (`wg`) + iproute2 (`ip`) are required for the WireGuard
# product protocol (Phase 11). The container must also run with the NET_ADMIN
# capability to create/manage the interface (see docker-compose / install docs).
RUN apt-get update \
    && apt-get install -y --no-install-recommends wireguard-tools iproute2 procps \
    && rm -rf /var/lib/apt/lists/*

RUN SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && rm -rf "${SITE:?}"/* \
    && mkdir -p /var/lib/nexuspanel-node "${SITE}"

COPY --from=build /nexuspanel-export/site-packages/ /tmp/nexuspanel-site-packages/
RUN SITE="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && cp -a /tmp/nexuspanel-site-packages/. "${SITE}/" \
    && rm -rf /tmp/nexuspanel-site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /usr/local/share/xray /usr/local/share/xray
COPY . /code

ENV SERVICE_PROTOCOL=rpyc
VOLUME ["/var/lib/nexuspanel-node"]

CMD ["bash", "-c", "python main.py"]
