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

COPY . /code

RUN test -f /code/app/dashboard-v2/build/index.html -o -f /code/app/dashboard/build/index.html \
    || (echo "ERROR: dashboard not built. Run: cd app/dashboard-v2 && npm install && npm run build" && exit 1)

RUN ln -sf /code/nexuspanel-cli.py /usr/bin/nexuspanel-cli \
    && chmod +x /usr/bin/nexuspanel-cli

CMD ["bash", "-c", "alembic upgrade head && exec python main.py"]
