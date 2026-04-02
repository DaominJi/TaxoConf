#!/usr/bin/env bash
# Start the TaxoConf server.
# Usage:
#   ./run_server.sh              # default: http://127.0.0.1:8000
#   ./run_server.sh --port 9000  # custom port
#   ./run_server.sh --reload     # auto-reload on code changes

set -euo pipefail
cd "$(dirname "$0")"

# Install dependencies if needed
if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "Installing dependencies..."
  pip install -r requirements.txt
fi

echo "Starting TaxoConf server..."
python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 "$@"
