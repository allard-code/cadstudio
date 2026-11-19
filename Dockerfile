# CAD-Studio: web-editor + MCP-server (streamable HTTP op /mcp) in één container.
FROM python:3.13-slim

# OpenCascade (OCP) linkt tegen libGL; fonts zijn nodig voor Text() in build123d.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libexpat1 fontconfig fonts-dejavu-core fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY pyproject.toml README.md ./
COPY cadstudio ./cadstudio
RUN pip install --no-cache-dir --no-deps . \
 && python -c "import build123d, cadstudio.web; print('import ok')"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data

ENV CADSTUDIO_HOME=/data \
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

# start als root, entrypoint regelt rechten op /data en draait verder als PUID:PGID (standaard 1000:1000)
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "cadstudio", "serve"]
