#!/bin/sh
set -e

# Userspace mode: Railway containers don't have /dev/net/tun or NET_ADMIN,
# so kernel-mode WireGuard networking isn't available — this runs Tailscale's
# netstack entirely in userspace instead. Inbound connections to this node's
# Tailscale IP are forwarded automatically to the same port on localhost, so
# nothing else has to be done for the app (listening on $PORT below) to be
# reachable from other tailnet devices.
/usr/local/bin/tailscaled \
  --tun=userspace-networking \
  --socks5-server=localhost:1055 \
  --state=/var/lib/tailscale/tailscaled.state &

# tailscaled needs a moment to start accepting commands after being backgrounded.
for i in $(seq 1 15); do
  if /usr/local/bin/tailscale up --auth-key="${TS_AUTHKEY}" --hostname=fintrack-backend; then
    echo "Tailscale connected."
    break
  fi
  echo "Waiting for tailscaled to be ready (attempt $i)..."
  sleep 1
done

echo "Starting app on port ${PORT:-8000}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
