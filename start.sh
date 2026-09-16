#!/usr/bin/env bash
# Idempotent starter for the GPU sizing calculator on port 8765.
set -u
DIR=/home/jeff/projects/gpu-sizing
LOG=$DIR/gpu-sizing.log
PIDF=$DIR/gpu-sizing.pid
PY=/home/jeff/miniforge3/bin/python
PORT=8765

if curl -sf -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/"; then
  exit 0  # already serving
fi

cd "$DIR" || exit 1
nohup "$PY" -m streamlit run app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false \
  >> "$LOG" 2>&1 &
echo $! > "$PIDF"

# wait for readiness (max ~20s)
for i in $(seq 1 20); do
  if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/"; then
    echo "gpu-sizing up on port $PORT (pid $(cat "$PIDF"))"
    exit 0
  fi
  sleep 1
done
echo "gpu-sizing started but not ready yet — check $LOG" >&2
exit 1
