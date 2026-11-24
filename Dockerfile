# CAD-Studio: web editor + MCP server (streamable HTTP on /mcp) in one container.

# --- OrcaSlicer (command line slicing for slice_plate) -------------------------------------------------
# The release AppImage is unpacked (no FUSE needed at runtime). Its vendor profiles ship packed, so the
# printer/process/filament JSON profiles are taken from the matching source tag.
FROM debian:trixie-slim AS orca
ARG ORCA_VERSION=2.5.2
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl -fsSL -o orca.AppImage \
      "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${ORCA_VERSION}/OrcaSlicer_Linux_AppImage_Ubuntu2404_V${ORCA_VERSION}.AppImage" \
 && chmod +x orca.AppImage && ./orca.AppImage --appimage-extract >/dev/null \
 && mv squashfs-root /opt/orca && rm orca.AppImage
RUN git clone -q --depth 1 --branch "v${ORCA_VERSION}" --filter=blob:none --sparse \
      https://github.com/OrcaSlicer/OrcaSlicer orca-src \
 && git -C orca-src sparse-checkout set --no-cone '/resources/profiles/*.json' '/resources/profiles/*/machine/' \
      '/resources/profiles/*/process/' '/resources/profiles/*/filament/' \
 && mkdir -p /opt/orca-profiles && cp -r orca-src/resources/profiles/. /opt/orca-profiles/ \
 && test -f "/opt/orca-profiles/Anycubic/machine/Anycubic Kobra S1 0.4 nozzle.json" \
 && rm -rf orca-src

# --- CAD-Studio ---------------------------------------------------------------------------------------
FROM python:3.13-slim

# OpenCascade (OCP) links against libGL; fonts are needed for Text() in build123d.
# The rest are OrcaSlicer's runtime libraries (it links GTK/WebKit even when only the CLI is used).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libexpat1 fontconfig fonts-dejavu-core fonts-liberation \
      libgtk-3-0t64 libwebkit2gtk-4.1-0 libegl1 libglu1-mesa libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
      libsecret-1-0 libdbus-1-3 libosmesa6 libsm6 libice6 libavcodec61 libavformat61 libavutil59 libswscale8 libmspack0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=orca /opt/orca /opt/orca
COPY --from=orca /opt/orca-profiles /opt/orca-profiles

WORKDIR /app
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY cadstudio ./cadstudio
RUN pip install --no-cache-dir --no-deps . \
 && python -c "import build123d, cadstudio.web; print('import ok')"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data

ENV CADSTUDIO_HOME=/data \
    CADSTUDIO_ORCA_HOME=/opt/orca \
    CADSTUDIO_ORCA_PROFILES=/opt/orca-profiles \
    CADSTUDIO_HOST=0.0.0.0 \
    CADSTUDIO_PORT=8765 \
    CADSTUDIO_IN_DOCKER=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp \
    PUID=1000 \
    PGID=1000

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"CADSTUDIO_PORT\"]}/health', timeout=4)" || exit 1

# starts as root; the entrypoint fixes ownership of /data and then drops to PUID:PGID (default 1000:1000)
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "cadstudio", "serve"]
