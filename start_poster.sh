#!/bin/bash
# Start the Landing Clinic outreach poster (local-only, localhost:8099).
cd "$(dirname "$0")"
if [ ! -f config.json ]; then
  echo "config.json not found. Copy it first:"
  echo "  cp config.example.json config.json"
  echo "Then fill in your Reddit app credentials (see README.md)."
  exit 1
fi
chmod 600 config.json
exec python3 server.py
