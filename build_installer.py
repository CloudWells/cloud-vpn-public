#!/usr/bin/env python3
import base64
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

manager_path = os.path.join(BASE_DIR, "vpn_manager.py")
vpn_sh_path = os.path.join(BASE_DIR, "vpn.sh")
installer_path = os.path.join(BASE_DIR, "install.sh")

# Read local vpn_manager.py and base64 encode
with open(manager_path, "rb") as f:
    manager_b64 = base64.b64encode(f.read()).decode("utf-8")

# Read local vpn.sh and base64 encode
with open(vpn_sh_path, "rb") as f:
    vpn_sh_b64 = base64.b64encode(f.read()).decode("utf-8")

# Format into self-contained installer script (completely generic, no tokens)
installer_content = f"""#!/usr/bin/env bash
# Cloud VPN Auto-Installer
# 100% Self-Contained, generic open-source release.
set -e

echo "Starting Cloud VPN installation..."

# Prompt user for subscription URL at the very beginning
echo "=================================================="
read -p "Please enter your VPN subscription URL (or press Enter to skip): " SUB_URL
echo "=================================================="

# 1. Verify basic dependencies
for cmd in curl python3; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "ERROR: Required dependency '$cmd' is not installed."
        exit 1
    fi
done

# 2. Setup the installation directory
TARGET_DIR="/opt/cloud-vpn"
echo "Setting up installation directory at $TARGET_DIR..."
mkdir -p "$TARGET_DIR"

# 3. Unpack self-contained software scripts locally
echo "Unpacking Cloud VPN software..."

cat << 'EOF' | base64 -d > "$TARGET_DIR/vpn_manager.py"
{manager_b64}
EOF

cat << 'EOF' | base64 -d > "$TARGET_DIR/vpn.sh"
{vpn_sh_b64}
EOF

# 4. Configure permissions
chmod +x "$TARGET_DIR/vpn_manager.py" "$TARGET_DIR/vpn.sh"

# 5. Bootstrap the VPN manager
echo "Initializing proxy engine..."
if [ -n "$SUB_URL" ]; then
    python3 "$TARGET_DIR/vpn_manager.py" update "$SUB_URL"
else
    # Just download sing-box core without subscription list
    python3 "$TARGET_DIR/vpn_manager.py" update "" || true
fi

# 6. Install the global vpn command
echo "Deploying global 'vpn' command..."
rm -f /usr/local/bin/vpn
ln -sf "$TARGET_DIR/vpn.sh" /usr/local/bin/vpn

echo "=================================================="
echo "Cloud VPN installed successfully!"
if [ -z "$SUB_URL" ]; then
    echo "   "
    echo "   Note: You must import your server subscription list."
    echo "      Run this command to fetch your servers:"
    echo "      vpn update \\"YOUR_SUBSCRIPTION_URL\\""
    echo "   "
fi
echo "   Try running 'vpn list' to see available locations."
echo "=================================================="
"""

with open(installer_path, "w", encoding="utf-8") as f:
    f.write(installer_content)

print("Public self-contained install.sh with interactive prompt compiled successfully!")
