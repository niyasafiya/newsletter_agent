#!/bin/zsh
# Starts the Flask backend (technomak_app.py) with the AI keys loaded.
#
#   ./start_backend.sh          then open http://localhost:8443/admin (React site)
#                               or http://127.0.0.1:5050/admin (Flask directly)
#
# Keys are read from ~/.technomak_keys (only its `export ...` lines), so they
# never live in this project folder. Put ADMIN_PASSWORD there too if you want
# a fixed admin password; otherwise a one-time one is printed below.
#
# Port 5050, not 5000: macOS's AirPlay Receiver already uses 5000. The
# React dev server (8443) is started with BACKEND_URL=http://127.0.0.1:5050.
cd "$(dirname "$0")"
[ -f ~/.technomak_keys ] && eval "$(grep '^export ' ~/.technomak_keys)"
exec ~/.venvs/technomak/bin/flask --app technomak_app run \
  --host 127.0.0.1 --port "${BACKEND_PORT:-5050}"
