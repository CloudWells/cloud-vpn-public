# Cloud VPN Client CLI (Open-Source Edition)

High-performance, fully automated, and privacy-focused VLESS / Reality / gRPC VPN client CLI designed for modern Ubuntu/Debian production environments.

This client is built on top of the ultra-lightweight and secure **`sing-box` (v1.13.12)** core. This public repository release is **entirely generic and stripped of any personal credentials, keys, or subscription routes**. Anyone can fork, deploy, and use it with their own server subscriptions.

---

## Technical Architecture & Advantages

1. **Interactive Installation**: Upon running, the installer dynamically prompts you to enter your private VPN subscription link. It parses your servers, downloads the sing-box core, and registers your client instantly.
2. **Mixed Inbound (Single Port)**: Employs the native `mixed` protocol in the sing-box core, allowing it to seamlessly handle both **SOCKS5** and **HTTP** proxy traffic on the **exact same port** (e.g., `1080`). No more port collisions or multiple port configurations.
3. **Multi-User Sandbox (Zero-Conflict)**:
   * System-wide scripts, executable binaries, and the shared server database cache are installed to the read-only directory `/opt/cloud-vpn/`.
   * All dynamic run-time assets (generated connection configs `config.json`, logs `sing-box.log`, active process PID files) are isolated to the home directory of the executing user: `~/.cloud-vpn/`.
   * **Result**: Regular non-root users can launch, monitor, and terminate VPN tunnels without `sudo` privileges and with zero risk of file permission errors.
4. **Smart Protocol Fallback (Auto-Fallback)**: Official sing-box core does not support Xray's proprietary `xHTTP` transport. If an `xHTTP` server is selected, the CLI automatically falls back to the equivalent TCP/Vision variant for that location.

---

## One-Command Production Installation

Execute the installation via the following **Python 3** command (replace `CloudWells` with your own GitHub username if you fork the project):

```bash
python3 -c "import urllib.request; req=urllib.request.Request('https://raw.githubusercontent.com/CloudWells/cloud-vpn-public/main/install.sh', headers={'User-Agent': 'Mozilla/5.0'}); print(urllib.request.urlopen(req).read().decode('utf-8'))" | sudo bash
```

The installer will prompt you to paste your private subscription URL, locally unpack all scripts, and configure the global `vpn` command.

---

## Command Line Interface (CLI) Reference

Once installed, the global `vpn` command is accessible globally by any system user.

### 1. `vpn list`
Displays all available parsed VPN servers organized by country index and transport protocol (TCP, gRPC, xHTTP).
```bash
vpn list
```

### 2. `vpn session [Index / Country Name]`
**Isolated Terminal Proxy Session (Most Popular Mode)**.
1. Automatically identifies a random free local port.
2. Launches sing-box in the background bound to that port.
3. Exports proxy environment variables (`http_proxy`, `https_proxy`, `all_proxy` and uppercase equivalents) set to `http://127.0.0.1:port` into the current shell.
4. Spawns a nested shell session with a `(vpn)` prefix on the prompt.
5. All CLI tools (`curl`, `git`, `python`, `apt`, `docker`, etc.) run inside this nested session are automatically routed through the secure VPN.
6. Typing `exit` or hitting `Ctrl+D` safely kills the background proxy process, unsets the environment variables, and returns you to your clean shell.
```bash
vpn session 1
vpn session Sweden
```

### 3. `vpn start [Index / Country Name] [Port]`
Starts the VPN client as a background daemon process on a specified local port (defaults to `1080`). It acts as a mixed SOCKS5 and HTTP proxy.
```bash
vpn start 4
vpn start USA 1085
```

### 4. `vpn status`
Checks if the background VPN daemon of the executing user is active, printing its active port.
```bash
vpn status
```

### 5. `vpn stop`
Safely stops the active background VPN daemon of the executing user, clearing PID files and ports.
```bash
vpn stop
```

### 6. `vpn update [Subscription URL]`
Forces a refresh of the local server database by fetching the latest configs from the panel and updates the sing-box core binary.
```bash
vpn update "https://your-subscription-url-here"
```

---

## Systemd Integration (Persistent Background Service)

You can configure the VPN tunnel to start automatically on system boot as a persistent background system service (requires `sudo` privileges).

### Install the service:
Deploys a systemd service pointing to a specified server (e.g. Sweden) bound to a port (e.g. `1080`):
```bash
sudo vpn install-service Sweden 1080
```
This registers, enables, and boots up a system service named `cloud-vpn.service`.

### System Service Control Commands:
```bash
sudo systemctl status cloud-vpn
sudo systemctl restart cloud-vpn
sudo systemctl stop cloud-vpn
```

### Uninstall the service:
```bash
sudo vpn uninstall-service
```
