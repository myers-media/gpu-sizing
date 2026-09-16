#!/usr/bin/env bash
set -u
DIR=/home/jeff/projects/gpu-sizing
PIDF=$DIR/gpu-sizing.pid
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  kill "$(cat "$PIDF")" && echo "stopped gpu-sizing (pid $(cat "$PIDF"))"
else
  pkill -f "streamlit run app.py.*8765" 2>/dev/null && echo "stopped gpu-sizing (pkill)" || echo "not running"
fi
rm -f "$PIDF"
