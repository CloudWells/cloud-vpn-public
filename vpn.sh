#!/usr/bin/env bash
# Cloud VPN Client CLI Wrapper

# Get the actual directory of this script, resolving any symlinks
REAL_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
DIR="$(dirname "$REAL_PATH")"

# Run the Python manager with all passed arguments
python3 "$DIR/vpn_manager.py" "$@"
