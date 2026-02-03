#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate

# Start the progress dashboard in the background
echo "Starting progress dashboard on http://localhost:${DASHBOARD_PORT:-8890}"
python ./progress_dashboard.py &
DASHBOARD_PID=$!

# Cleanup dashboard when transcription stops
cleanup() {
    echo "Stopping dashboard (PID: $DASHBOARD_PID)"
    kill $DASHBOARD_PID 2>/dev/null || true
}
trap cleanup EXIT

# Start the transcription service (foreground)
echo "Starting transcription service..."
python ./transcribe_all.py
