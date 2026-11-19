#!/bin/sh
# Zorgt dat /data schrijfbaar is voor PUID:PGID (standaard 1000:1000) en draait dan zonder root-rechten.
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data
  if [ "$(stat -c %u /data)" != "$PUID" ]; then
    chown -R "$PUID:$PGID" /data
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups env HOME=/tmp "$@"
fi
exec "$@"
