#!/usr/bin/env python3
import os
import sys
import json
import base64
import socket
import signal
import subprocess
import time
from urllib.parse import urlparse, parse_qs, unquote
import urllib.request
import tarfile
import io

# Setup user-specific paths to avoid root permission conflicts
HOME_DIR = os.path.expanduser("~")
USER_DIR = os.path.join(HOME_DIR, ".cloud-vpn")
os.makedirs(USER_DIR, exist_ok=True)

# Base installation directory (shared)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = "/opt/cloud-vpn"

# Dynamic runtime files (must write into user's home directory)
CONFIG_FILE = os.path.join(USER_DIR, "config.json")
PID_FILE = os.path.join(USER_DIR, "sing-box.pid")
LOG_FILE = os.path.join(USER_DIR, "sing-box.log")
SERVICE_CONFIG_FILE = os.path.join(SHARED_DIR, "service_config.json") if os.path.exists(SHARED_DIR) else os.path.join(BASE_DIR, "service_config.json")

# Default subscription URL is empty for public safety.
# Users must run: vpn update <url> on their first run.
DEFAULT_SUB_URL = ""

def get_servers_file_path():
    """Detects and returns the best path to read/write servers.json."""
    shared_path = os.path.join(SHARED_DIR, "servers.json")
    if os.path.exists(shared_path):
        return shared_path
    
    local_shared = os.path.join(BASE_DIR, "servers.json")
    if os.path.exists(local_shared):
        return local_shared
        
    return os.path.join(USER_DIR, "servers.json")

def get_servers_write_path():
    """Detects where to write servers.json during an update."""
    shared_servers = os.path.join(SHARED_DIR, "servers.json")
    if os.access(SHARED_DIR, os.W_OK) or (os.path.exists(shared_servers) and os.access(shared_servers, os.W_OK)):
        return shared_servers
    return os.path.join(USER_DIR, "servers.json")

def download_singbox():
    """Downloads and extracts the official sing-box binary."""
    # 1. Check shared binary first
    shared_sb = os.path.join(SHARED_DIR, "bin", "sing-box")
    if os.path.exists(shared_sb):
        return shared_sb
        
    local_shared_sb = os.path.join(BASE_DIR, "bin", "sing-box")
    if os.path.exists(local_shared_sb):
        return local_shared_sb
        
    # 2. Check or download to user-local directory
    sb_dir = os.path.join(USER_DIR, "bin")
    sb_path = os.path.join(sb_dir, "sing-box")
    if os.path.exists(sb_path):
        return sb_path
        
    os.makedirs(sb_dir, exist_ok=True)
    
    print("sing-box binary not found. Downloading SagerNet/sing-box v1.13.12...")
    url = "https://github.com/SagerNet/sing-box/releases/download/v1.13.12/sing-box-1.13.12-linux-amd64.tar.gz"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            tar_data = response.read()
            
        print("Extracting sing-box binary...")
        with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tar_ref:
            for member in tar_ref.getmembers():
                if member.name.endswith("/sing-box") or member.name == "sing-box":
                    f = tar_ref.extractfile(member)
                    if f:
                        with open(sb_path, "wb") as out_f:
                            out_f.write(f.read())
                        break
                        
        os.chmod(sb_path, 0o755)
        print("sing-box installed successfully!")
        return sb_path
    except Exception as e:
        print(f"Warning: Python-native tar download/extract failed ({e}).")
        print("Trying fallback via curl and tar...")
        
        tar_path = os.path.join(sb_dir, "sing-box.tar.gz")
        os.system(f"curl -sL \"{url}\" -o \"{tar_path}\"")
        os.system(f"tar -xzf \"{tar_path}\" -C \"{sb_dir}\" --wildcards \"*/sing-box\" --strip-components=1")
        if os.path.exists(tar_path):
            os.remove(tar_path)
            
        if os.path.exists(sb_path):
            os.chmod(sb_path, 0o755)
            print("sing-box installed successfully via fallback!")
            return sb_path
        else:
            print("ERROR: Failed to download sing-box binary.")
            sys.exit(1)

def parse_vless_link(link):
    """Parses a VLESS link into a structured dict."""
    parsed = urlparse(link)
    if parsed.scheme != 'vless':
        return None
        
    netloc = parsed.netloc
    if '@' in netloc:
        user_info, host_port = netloc.split('@', 1)
        uuid = user_info
    else:
        uuid = parsed.username
        host_port = parsed.netloc
        
    if ':' in host_port:
        host, port_str = host_port.split(':', 1)
        port = int(port_str)
    else:
        host = host_port
        port = 443
        
    query_params = parse_qs(parsed.query)
    params = {k: v[0] for k, v in query_params.items()}
    
    name = unquote(parsed.fragment) if parsed.fragment else f"{host}:{port}"
    
    extra_data = None
    if 'extra' in params:
        try:
            extra_data = json.loads(unquote(params['extra']))
        except Exception:
            try:
                extra_data = json.loads(params['extra'])
            except Exception:
                pass
                
    return {
        'uuid': uuid,
        'host': host,
        'port': port,
        'name': name,
        'security': params.get('security', 'none'),
        'type': params.get('type', 'tcp'),
        'flow': params.get('flow', ''),
        'sni': params.get('sni', ''),
        'fp': params.get('fp', 'chrome'),
        'pbk': params.get('pbk', ''),
        'sid': params.get('sid', ''),
        'serviceName': params.get('serviceName', ''),
        'path': params.get('path', ''),
        'host_header': params.get('host', ''),
        'mode': params.get('mode', ''),
        'extra': extra_data
    }

def update_subscription(sub_url=DEFAULT_SUB_URL):
    """Fetches the subscription, decodes base64, parses VLESS links, and saves them."""
    if not sub_url:
        print("ERROR: No subscription URL configured.")
        print("Please provide your subscription link by running:")
        print("vpn update \"https://your-subscription-url-here\"")
        return None
        
    print(f"Fetching subscription from: {sub_url}")
    try:
        req = urllib.request.Request(sub_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw_data = response.read().decode('utf-8').strip()
            
        missing_padding = len(raw_data) % 4
        if missing_padding:
            raw_data += '=' * (4 - missing_padding)
            
        try:
            decoded_data = base64.b64decode(raw_data).decode('utf-8')
        except Exception:
            decoded_data = raw_data
            
        links = [line.strip() for line in decoded_data.split('\n') if line.strip().startswith('vless://')]
        
        parsed_servers = []
        for index, link in enumerate(links):
            try:
                srv = parse_vless_link(link)
                if srv:
                    srv['index'] = index + 1
                    parsed_servers.append(srv)
            except Exception as e:
                print(f"Warning: Failed to parse link {link[:50]}... : {e}")
                
        write_path = get_servers_write_path()
        with open(write_path, 'w', encoding='utf-8') as f:
            json.dump(parsed_servers, f, indent=2, ensure_ascii=False)
            
        print(f"Successfully downloaded and parsed {len(parsed_servers)} servers!")
        return parsed_servers
    except Exception as e:
        print(f"Error updating subscription: {e}")
        return None

def load_servers():
    """Loads parsed servers from local file, auto-updating if missing."""
    servers_file = get_servers_file_path()
    if not os.path.exists(servers_file):
        print("ERROR: Local server list missing. Please perform an initial update with your subscription URL:")
        print("vpn update \"https://your-subscription-url-here\"")
        sys.exit(1)
        
    try:
        with open(servers_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        print("Error reading servers file. Please run vpn update again.")
        sys.exit(1)

def find_free_port():
    """Finds an unused port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def generate_singbox_config(server, listen_port):
    """Generates the sing-box config.json for the chosen server."""
    inbounds = [
        {
            "type": "mixed",
            "tag": "mixed-in",
            "listen": "127.0.0.1",
            "listen_port": int(listen_port)
        }
    ]
    
    outbound = {
        "type": "vless",
        "tag": "vless-out",
        "server": server["host"],
        "server_port": int(server["port"]),
        "uuid": server["uuid"]
    }
    
    if server["type"] == "tcp" and server.get("flow"):
        outbound["flow"] = server["flow"]
        
    tls_settings = {
        "enabled": True,
        "server_name": server.get("sni", ""),
        "utls": {
            "enabled": True,
            "fingerprint": server.get("fp", "chrome")
        }
    }
    
    if server["security"] == "reality":
        tls_settings["reality"] = {
            "enabled": True,
            "public_key": server.get("pbk", ""),
            "short_id": server.get("sid", "")
        }
        
    outbound["tls"] = tls_settings
    
    if server["type"] == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": server.get("serviceName", "grpc-internal-stream")
        }
        
    outbounds = [
        outbound,
        {
            "type": "direct",
            "tag": "direct-out"
        }
    ]
    
    config = {
        "log": {
            "level": "warn"
        },
        "inbounds": inbounds,
        "outbounds": outbounds
    }
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def check_and_apply_fallback(server, servers):
    """If server uses xhttp, falls back to the corresponding TCP server."""
    if server["type"] == "xhttp":
        print("Note: xHTTP protocol is not natively supported in sing-box.")
        clean_name = server["name"].split("[")[0].strip()
        for s in servers:
            if s["type"] == "tcp" and s["name"].split("[")[0].strip() == clean_name:
                print(f"Automatically fell back to TCP variant: {s['name']}")
                return s
        for s in servers:
            if s["type"] == "tcp":
                print(f"Automatically fell back to TCP server: {s['name']}")
                return s
    return server

def is_pid_alive(pid):
    """Checks if a process ID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def is_singbox_running():
    """Checks if the background sing-box process is active."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        return is_pid_alive(pid)
    except Exception:
        return False

def start_singbox(server, listen_port):
    """Starts sing-box in the background."""
    sb_bin = download_singbox()
    servers = load_servers()
    server = check_and_apply_fallback(server, servers)
    
    generate_singbox_config(server, listen_port)
    
    if is_singbox_running():
        print("VPN is already running. Restarting it...")
        stop_singbox()
        
    log_file = open(LOG_FILE, 'w')
    
    try:
        proc = subprocess.Popen(
            [sb_bin, "run", "-c", CONFIG_FILE],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=USER_DIR,
            preexec_fn=os.setsid
        )
        
        with open(PID_FILE, 'w') as f:
            f.write(str(proc.pid))
            
        time.sleep(1.5)
        if proc.poll() is not None:
            print("ERROR: VPN failed to start. View ~/.cloud-vpn/sing-box.log for details:")
            with open(LOG_FILE, 'r') as lf:
                print(lf.read())
            return False
            
        print("VPN started successfully in background!")
        print(f"Server: {server['name']}")
        print(f"Local Port: {listen_port} (Supports SOCKS5 & HTTP proxy)")
        return True
    except Exception as e:
        print(f"ERROR: Failed to start VPN: {e}")
        return False

def stop_singbox():
    """Stops the background sing-box process."""
    if not os.path.exists(PID_FILE):
        print("INFO: No background VPN is running.")
        return False
        
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
            
        print(f"Stopping VPN client (PID {pid})...")
        
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
                
        for _ in range(10):
            if not is_pid_alive(pid):
                break
            time.sleep(0.2)
            
        if is_pid_alive(pid):
            print("Force stopping VPN client...")
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                    
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            
        print("VPN stopped.")
        return True
    except Exception as e:
        print(f"ERROR: Failed to stop VPN: {e}")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return False

def find_server_by_query(query, servers):
    """Finds a server by index or fuzzy matches name/country."""
    try:
        idx = int(query)
        for s in servers:
            if s["index"] == idx:
                return s
    except ValueError:
        pass
        
    query_lower = query.lower()
    for s in servers:
        if query_lower in s["name"].lower():
            return s
            
    return None

def print_servers_list(servers):
    """Prints all parsed servers in a neat format."""
    print("\n--- Available VPN Servers ---")
    for s in servers:
        print(f" [{s['index']}] {s['name']}")
    print("-----------------------------\n")

def run_session(server):
    """Runs a nested proxy shell session."""
    sb_bin = download_singbox()
    servers = load_servers()
    server = check_and_apply_fallback(server, servers)
    
    listen_port = find_free_port()
    generate_singbox_config(server, listen_port)
    
    log_file = open(LOG_FILE, 'w')
    
    try:
        proc = subprocess.Popen(
            [sb_bin, "run", "-c", CONFIG_FILE],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=USER_DIR,
            preexec_fn=os.setsid
        )
        
        time.sleep(1.2)
        if proc.poll() is not None:
            print("ERROR: VPN failed to start. View ~/.cloud-vpn/sing-box.log for details.")
            return False
            
        env = os.environ.copy()
        proxy_url = f"http://127.0.0.1:{listen_port}"
        socks_url = f"socks5://127.0.0.1:{listen_port}"
        
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url
        env["all_proxy"] = socks_url
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
        env["ALL_PROXY"] = socks_url
        env["VPN_SESSION_ACTIVE"] = "1"
        env["VPN_SERVER_NAME"] = server["name"]
        
        if "PS1" in env:
            env["PS1"] = f"(vpn) {env['PS1']}"
        else:
            env["PS1"] = "(vpn) \\u@\\h:\\w\\$ "
            
        shell = os.environ.get("SHELL", "/bin/bash")
        
        print("\n" + "="*55)
        print("ENTERING LOCAL VPN SESSION")
        print(f"   Route: {server['name']}")
        print(f"   Local Port: {listen_port} (SOCKS5 & HTTP)")
        print("   Your current terminal session is now under VPN protection.")
        print("   Type 'exit' to quit the session and disconnect.")
        print("="*55 + "\n")
        
        subprocess.run([shell], env=env)
        
        print("\n" + "="*55)
        print("EXITING VPN SESSION")
        print("   Stopping VPN tunnel and restoring network settings...")
        
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
                
        print("   Cleaned up. Goodbye!")
        print("="*55 + "\n")
        
    except Exception as e:
        print(f"ERROR: Failed during VPN session: {e}")

def get_systemd_user():
    """Tries to find the current login user, fallback to 'cloud'."""
    user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    if user == "root":
        try:
            import pwd
            for p in pwd.getpwall():
                if p.pw_uid >= 1000 and p.pw_name != "nobody":
                    return p.pw_name
        except ImportError:
            pass
    return user or "cloud"

def install_systemd_service(server, listen_port):
    """Installs the VPN client as a systemd background service."""
    svc_config = {
        "server_index": server["index"],
        "listen_port": int(listen_port)
    }
    with open(SERVICE_CONFIG_FILE, 'w') as f:
        json.dump(svc_config, f, indent=2)
        
    username = get_systemd_user()
    
    service_content = f"""[Unit]
Description=Cloud VPN Service (Server {server['index']}: {server['name']})
After=network.target

[Service]
Type=simple
WorkingDirectory={SHARED_DIR if os.path.exists(SHARED_DIR) else BASE_DIR}
ExecStart=/usr/bin/python3 {os.path.abspath(__file__)} run-service
Restart=always
User={username}

[Install]
WantedBy=multi-user.target
"""
    
    service_file_path = "/etc/systemd/system/cloud-vpn.service"
    
    print("Installing systemd service (cloud-vpn)...")
    try:
        temp_path = os.path.join(USER_DIR, "cloud-vpn.service.tmp")
        with open(temp_path, 'w') as f:
            f.write(service_content)
            
        print("Executing sudo commands to configure service...")
        subprocess.run(["sudo", "mv", temp_path, service_file_path], check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "cloud-vpn"], check=True)
        subprocess.run(["sudo", "systemctl", "start", "cloud-vpn"], check=True)
        
        print("Systemd service 'cloud-vpn' installed, enabled, and started successfully!")
        print("You can check status with: systemctl status cloud-vpn")
    except Exception as e:
        print(f"ERROR: Failed to install systemd service: {e}")
        print("Note: Root/sudo privileges are required for systemd installations.")

def uninstall_systemd_service():
    """Uninstalls the systemd service."""
    service_file_path = "/etc/systemd/system/cloud-vpn.service"
    print("Uninstalling systemd service (cloud-vpn)...")
    try:
        subprocess.run(["sudo", "systemctl", "stop", "cloud-vpn"], stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "systemctl", "disable", "cloud-vpn"], stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "rm", "-f", service_file_path], check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        print("Systemd service 'cloud-vpn' has been uninstalled.")
    except Exception as e:
        print(f"ERROR: Failed to uninstall systemd service: {e}")

def run_service_foreground():
    """Runs the service in the foreground (used by systemd service)."""
    if not os.path.exists(SERVICE_CONFIG_FILE):
        print(f"Config file {SERVICE_CONFIG_FILE} missing. Using defaults.")
        svc_config = {"server_index": 1, "listen_port": 1080}
    else:
        with open(SERVICE_CONFIG_FILE, 'r') as f:
            svc_config = json.load(f)
            
    servers = load_servers()
    server = None
    target_idx = svc_config.get("server_index", 1)
    for s in servers:
        if s["index"] == target_idx:
            server = s
            break
            
    if not server:
        if servers:
            server = servers[0]
        else:
            print("ERROR: No VPN servers found.")
            sys.exit(1)
            
    server = check_and_apply_fallback(server, servers)
    listen_port = svc_config.get("listen_port", 1080)
    
    sb_bin = download_singbox()
    generate_singbox_config(server, listen_port)
    
    print("Starting sing-box in foreground for service...")
    print(f"Server: {server['name']}")
    print(f"Port: {listen_port}")
    
    subprocess.run([sb_bin, "run", "-c", CONFIG_FILE], cwd=USER_DIR)

def print_help():
    print("""=== Cloud VPN Client CLI ===
Usage:
  ./vpn [command] [options]

Commands:
  list                          List all available VPN servers
  update [sub_url]              Fetch and parse servers from subscription link
  start [idx/name] [port]       Start background VPN on port (default SOCKS/HTTP port: 1080)
  stop                          Stop background VPN
  status                        Check status of background VPN
  session [idx/name]            Start nested proxy shell session on auto free port
  install-service [idx] [port]  Install VPN as systemd system service on port
  uninstall-service             Uninstall the systemd system service

Examples:
  ./vpn update "https://your-subscription-url"
  ./vpn list
  ./vpn session 1
  ./vpn session Sweden
  ./vpn start Finland 1080
  ./vpn stop
""")

def main():
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)
        
    cmd = sys.argv[1].lower()
    
    if cmd == "update":
        sub_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SUB_URL
        update_subscription(sub_url)
        download_singbox()
        
    elif cmd == "list":
        servers = load_servers()
        print_servers_list(servers)
        
    elif cmd in ("start", "session", "install-service"):
        servers = load_servers()
        
        query = "1"
        if len(sys.argv) > 2:
            query = sys.argv[2]
            
        server = find_server_by_query(query, servers)
        if not server:
            print(f"ERROR: Server '{query}' not found.")
            print_servers_list(servers)
            sys.exit(1)
            
        if cmd == "start":
            listen_port = sys.argv[3] if len(sys.argv) > 3 else "1080"
            start_singbox(server, listen_port)
            
        elif cmd == "session":
            run_session(server)
            
        elif cmd == "install-service":
            listen_port = sys.argv[3] if len(sys.argv) > 3 else "1080"
            install_systemd_service(server, listen_port)
            
    elif cmd == "stop":
        stop_singbox()
        
    elif cmd == "status":
        if is_singbox_running():
            print("Background VPN is running.")
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r') as f:
                        cfg = json.load(f)
                    port = cfg["inbounds"][0]["listen_port"]
                    print(f"   Listening on local port: {port} (SOCKS5 & HTTP)")
                except Exception:
                    pass
        else:
            print("Background VPN is NOT running.")
            
    elif cmd == "uninstall-service":
        uninstall_systemd_service()
        
    elif cmd == "run-service":
        run_service_foreground()
        
    else:
        print_help()

if __name__ == "__main__":
    main()
