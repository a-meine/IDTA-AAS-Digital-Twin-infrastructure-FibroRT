# Universal AAS for Distributed Systems — Implementation Plan

> Status: Draft
> Created: 2026-07-21

---

## 1. Problem Statement

Currently, multiple independent BaSyx stacks (aas-environment + aas-registry) run on
different machines in the same LAN. There is no centralized way to:

- Discover which AAS servers exist on the network
- Browse all registered products across all servers
- Get a direct link to the actual server hosting a specific AAS

Each stack is isolated. To find data from another server, you must manually query
its registry or AAS Environment API.

---

## 2. Goal

Deploy a **central "Universal AAS"** on the existing machine (192.168.56.212) that
acts as a single discovery point for all AAS data across the distributed system.

- All remote AAS servers **automatically register** their shell descriptors with
  the central registry via a heartbeat mechanism.
- A **custom lightweight web UI** lets users browse all registered products and
  follow direct links to the actual server hosting each AAS.
- The central server holds only **metadata** (shell descriptors with endpoints),
  not the actual AAS data (submodels, concept descriptions).
- Shares the **existing Keycloak** for authentication (single sign-on).

---

## 3. Architecture

```
                            LAN (192.168.56.x)

  ┌──────────────────────── Machine A (192.168.56.212) ──────────────────────┐
  │                                                                          │
  │  ┌───────────────────┐   ┌────────────────────┐   ┌───────────────────┐  │
  │  │ Existing Stack     │   │ Universal Stack     │   │ Discovery UI      │  │
  │  │ aas-env:8081       │   │ central-registry    │   │ :3001             │  │
  │  │ aas-registry:8083  │   │ :8085               │   │ (custom dashboard)│  │
  │  │ nginx:8443         │   │                     │   │                   │  │
  │  │ keycloak:9443      │   │                     │   │                   │  │
  │  └───────────────────┘   └────────────────────┘   └───────────────────┘  │
  │                                                                          │
  │  nginx:8443 ── /universal/ ──> discovery-ui:3001                         │
  │  nginx:8443 ── /shells,... ──> existing aas-environment:8081             │
  └──────────────────────────────────────────────────────────────────────────┘

  ┌──── Machine B (192.168.56.213) ───┐  ┌──── Machine C (192.168.56.214) ──┐
  │  aas-env:8081                      │  │  aas-env:8081                     │
  │  aas-registry:8083                 │  │  aas-registry:8083                │
  │                                    │  │                                   │
  │  heartbeat-service                 │  │  heartbeat-service                │
  │    every 30s:                      │  │    every 30s:                     │
  │    GET local /registry/shells      │  │    GET local /registry/shells     │
  │    POST to central-registry:8085   │  │    POST to central-registry:8085  │
  └────────────────────────────────────┘  └───────────────────────────────────┘
```

---

## 4. Components

### 4.1 Central AAS Registry

A dedicated BaSyx AAS Registry instance on port 8085 (exposed) / 8080 (internal).

- Stores shell descriptors from **all** remote AAS servers
- Each shell descriptor includes endpoints pointing to the remote server's public IP
- Reuses existing MongoDB and Keycloak via the `basyx-shared` Docker network
- Authorization **enabled** — only `admin` and `registry-writer` roles can write

**Config: `universal-aas/central-registry.yml`**

```yaml
spring:
  mongodb:
    uri: mongodb://${MONGO_USERNAME}:${MONGO_PASSWORD}@mongo:27017/admin
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: https://${HOST_IP}:9443/realms/BaSyx
          jwk-set-uri: http://keycloak:8080/realms/BaSyx/protocol/openid-connect/certs
springdoc:
  api-docs:
    enabled: true
    path: /v3/api-docs
  swagger-ui:
    enabled: true
    path: /swagger-ui.html
basyx:
  feature:
    authorization:
      enabled: true
      type: rbac
      jwtBearerTokenProvider: keycloak
      rbac:
        file: file:/config/rbac_rules.json
  cors:
    allowed-origins: 'https://${HOST_IP}:8443,https://${HOST_IP}:8444'
    allowed-methods: GET,POST,PATCH,DELETE,PUT,OPTIONS,HEAD
```

### 4.2 Heartbeat Service

A lightweight Python script/container running on each remote AAS server.

**What it does:**

1. Every N seconds (default 30), fetch all shell descriptors from the local AAS
   Registry (`GET http://localhost:8083/shell-descriptors`)
2. Unwrap the BaSyx v3 response envelope (`{"paging_metadata":{},"result":[...]}`)
3. Transform endpoint addresses by parsing `protocolInformation.href` and replacing
   localhost/0.0.0.0 hostnames with the remote server's public IP
4. Base64-URL encode the AAS ID and PUT the shell descriptor to the central registry
5. Track which shells exist locally — if a shell is removed, DELETE it from the
   central registry

**Heartbeat registration flow:**

```
Remote Machine (192.168.56.213)
    │
    ├── 1. GET http://localhost:8083/shell-descriptors
    │      → {"paging_metadata":{},"result":[{id: "https://...", ...}]}
    │
    ├── 2. Unwrap envelope → [{id: "https://...", idShort: "ProductA", endpoints: [...]}]
    │
    ├── 3. Transform endpoints (parse protocolInformation.href):
    │      href: "http://localhost:8082/shells/..." → "http://192.168.56.213:8082/shells/..."
    │      endpointProtocol: "http" → "https"
    │
    ├── 4. Authenticate with Keycloak (client credentials grant)
    │      → JWT token with registry-writer role
    │
    ├── 5. Base64-URL encode AAS ID:
    │      "https://admin-shell.io/idta/aas/Test/1/0"
    │      → "aHR0cHM6Ly9hZG1pbi1zaGVsbC5pby9pZHRhL2Fhcy9UZXN0LzEvMA"
    │
    └── 6. PUT http://192.168.56.212:8085/shell-descriptors/{base64url-encoded-id}
           Headers: Authorization: Bearer <jwt>
           Body: {id: "...", idShort: "ProductA",
                  endpoints: [{interface: "AAS-3.0",
                               protocolInformation: {href: "...", endpointProtocol: "https"}}]}
```

**Shell descriptor format (BaSyx v3):**

```json
{
  "id": "https://admin-shell.io/idta/aas/ProductA/1/0",
  "idShort": "ProductA",
  "endpoints": [
    {
      "interface": "AAS-3.0",
      "protocolInformation": {
        "href": "http://192.168.56.213:8081/shells/aHR0cHM6Ly9h...",
        "endpointProtocol": "https"
      }
    }
  ]
}
```

> **Important:** BaSyx v3 shell descriptors use `protocolInformation` with `href`
> and `endpointProtocol` (not the older `host`/`port`/`protocol` format).
> AAS IDs must be **Base64-URL encoded** in URL paths, not standard percent-encoded.

### 4.3 Custom Discovery UI

A lightweight web application (Python Flask) serving a single-page dashboard.

**Features:**

- Product list: All shell descriptors from central registry, displayed as cards
- Search/filter: By AAS ID, ID short, or server IP
- Server overview: All registered servers with product counts and last-seen status
- Direct links: Each product links to the remote server's AAS Web UI
- Read-only: No editing capability

**Layout:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  Universal AAS Discovery                                            │
│                                                                     │
│  ┌─────────────────────────────────────────────┐  ┌──────────────┐  │
│  │  Search products...                          │  │ 3 Servers    │  │
│  └─────────────────────────────────────────────┘  │ 42 Products  │  │
│                                                    └──────────────┘  │
│  ┌─ Products ─────────────────────────────┐  ┌─ Servers ──────────┐ │
│  │                                         │  │                     │ │
│  │  ProductA                               │  │ 192.168.56.212     │ │
│  │  Server: 192.168.56.213                 │  │ 15 AAS | Last: 2m  │ │
│  │  Last seen: 2 min ago                   │  │                     │ │
│  │  [View on server →]                     │  │ 192.168.56.213     │ │
│  │                                         │  │ 20 AAS | Last: 1m  │ │
│  │  ProductB                               │  │                     │ │
│  │  Server: 192.168.56.214                 │  │ 192.168.56.214     │ │
│  │  Last seen: 5 min ago                   │  │  7 AAS | Last: 3m  │ │
│  │  [View on server →]                     │  │                     │ │
│  │                                         │  └─────────────────────┘ │
│  └─────────────────────────────────────────┘                         │
└─────────────────────────────────────────────────────────────────────┘
```

**API endpoints (Flask app):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve the dashboard HTML |
| GET | `/api/shells` | Proxy to central registry, return all shell descriptors |
| GET | `/api/servers` | Aggregate shells by server IP, return server status |
| GET | `/api/health/<ip>` | Check if a remote server is reachable |

---

## 5. File Structure

New files to create:

```
basyx-setup/
├── universal-aas/
│   ├── docker-compose.yml              # Central registry + discovery UI
│   ├── central-registry.yml            # Spring Boot config
│   ├── rbac_rules_central.json         # RBAC with registry-writer role
│   └── heartbeat/
│       ├── heartbeat.py                # Auto-registration script
│       ├── config.py                   # Configuration (URLs, intervals)
│       ├── requirements.txt            # requests
│       └── Dockerfile                  # Container for heartbeat
│
├── discovery-ui/
│   ├── app.py                          # Flask application
│   ├── templates/
│   │   └── index.html                  # Dashboard SPA
│   ├── static/
│   │   ├── style.css                   # Dashboard styling
│   │   └── app.js                      # Dashboard JavaScript (fetch, render)
│   ├── requirements.txt                # flask, requests
│   └── Dockerfile                      # Container for discovery UI
│
└── (modified) nginx/nginx.conf         # Add /universal/ location block
```

Files to modify:

```
├── nginx/nginx.conf                    # Add /universal/ → discovery-ui:3001
├── docker-compose.yml                  # Add basyx-shared network to existing services
└── keycloak/realm-export.json          # Add heartbeat client + registry-writer role
```

---

## 6. RBAC Rules — Central Registry

**`universal-aas/rbac_rules_central.json`:**

```json
[
  {
    "role": "admin",
    "action": ["CREATE", "READ", "UPDATE", "DELETE"],
    "targetInformation": {
      "@type": "aas-registry",
      "aasIds": "*",
      "submodelIds": "*"
    }
  },
  {
    "role": "reader",
    "action": "READ",
    "targetInformation": {
      "@type": "aas-registry",
      "aasIds": "*",
      "submodelIds": "*"
    }
  },
  {
    "role": "registry-writer",
    "action": ["CREATE", "READ", "UPDATE"],
    "targetInformation": {
      "@type": "aas-registry",
      "aasIds": "*",
      "submodelIds": "*"
    }
  }
]
```

---

## 7. Keycloak Changes

Add to `keycloak/realm-export.json`:

### 7.1 New Client: `heartbeat-registry`

```json
{
  "clientId": "heartbeat-registry",
  "enabled": true,
  "publicClient": false,
  "protocol": "openid-connect",
  "standardFlowEnabled": false,
  "directAccessGrantsEnabled": true,
  "serviceAccountsEnabled": true,
  "secret": "heartbeat-secret-change-me",
  "defaultClientScopes": ["openid"]
}
```

### 7.2 New Realm Role: `registry-writer`

```json
{
  "name": "registry-writer",
  "description": "Can register and update shell descriptors in the central registry",
  "composite": false
}
```

### 7.3 New Users (one per remote machine)

```json
{
  "username": "machine-b-heartbeat",
  "enabled": true,
  "credentials": [
    {
      "type": "password",
      "value": "heartbeat-password-change-me",
      "temporary": false
    }
  ],
  "realmRoles": ["registry-writer"]
}
```

---

## 8. nginx Changes

Add this location block inside the `server { listen 8443 ssl; }` block:

```nginx
# Universal AAS Discovery UI
location /universal/ {
    proxy_pass http://discovery-ui:3001/;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Port  $server_port;
}
```

The discovery UI will be accessible at: `https://192.168.56.212:8443/universal/`

---

## 9. Docker Compose — Central Stack

**`universal-aas/docker-compose.yml`:**

```yaml
services:
  central-registry:
    container_name: central-registry
    image: eclipsebasyx/aas-registry-log-mongodb:2.0.0-milestone-13
    restart: unless-stopped
    ports:
      - "8085:8080"
    environment:
      - SERVER_PORT=8080
      - HOST_IP=${HOST_IP}
      - MONGO_USERNAME=${MONGO_USERNAME}
      - MONGO_PASSWORD=${MONGO_PASSWORD}
    volumes:
      - ./central-registry.yml:/workspace/config/application.yml:ro
      - ./rbac_rules_central.json:/config/rbac_rules.json:ro
    depends_on:
      mongo:
        condition: service_healthy
      keycloak:
        condition: service_started
    networks:
      - basyx-shared

  discovery-ui:
    container_name: discovery-ui
    build: ../discovery-ui
    restart: unless-stopped
    environment:
      - CENTRAL_REGISTRY_URL=http://central-registry:8080
      - HOST_IP=${HOST_IP}
    depends_on:
      - central-registry
    networks:
      - basyx-shared

networks:
  basyx-shared:
    external: true
```

This compose file joins the existing `basyx-shared` network to reuse the
shared MongoDB and Keycloak containers.

---

## 10. Heartbeat Script — Implementation

**`universal-aas/heartbeat/heartbeat.py`:**

```python
#!/usr/bin/env python3
"""
Heartbeat service for registering local AAS shell descriptors
with the central Universal AAS registry.
"""

import time
import sys
import base64
import requests
from urllib.parse import urlparse
from config import (
    CENTRAL_REGISTRY_URL,
    LOCAL_REGISTRY_URL,
    MY_PUBLIC_IP,
    MY_PORT,
    MY_WEB_UI_URL,
    HEARTBEAT_INTERVAL,
    KEYCLOAK_URL,
    KEYCLOAK_CLIENT_ID,
    KEYCLOAK_CLIENT_SECRET,
    KEYCLOAK_REALM,
)


def b64url_encode(value: str) -> str:
    """Base64-URL encode a string (BaSyx v3 API requirement)."""
    return base64.urlsafe_b64encode(value.encode()).decode()


def unwrap_baaxyx_envelope(data):
    """Unwrap BaSyx v3 response envelope: {"paging_metadata":{},"result":[...]} -> list."""
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data if isinstance(data, list) else []


def get_jwt_token():
    """Authenticate with Keycloak and return a JWT token."""
    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": KEYCLOAK_CLIENT_SECRET,
    }
    resp = requests.post(url, data=data, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_local_shells():
    """Fetch all shell descriptors from the local AAS registry."""
    url = f"{LOCAL_REGISTRY_URL}/shell-descriptors"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return unwrap_baaxyx_envelope(resp.json())


def transform_endpoints(shells):
    """Replace localhost endpoints with this machine's public IP in protocolInformation.href."""
    for shell in shells:
        for ep in shell.get("endpoints", []):
            proto_info = ep.get("protocolInformation", {})
            href = proto_info.get("href", "")
            if href:
                parsed = urlparse(href)
                host = parsed.hostname or ""
                if host in ("localhost", "0.0.0.0", "127.0.0.1"):
                    proto_info["href"] = href.replace(host, MY_PUBLIC_IP)
            proto_info["endpointProtocol"] = "https"
    return shells


def get_central_shell_ids(token):
    """Fetch all shell descriptor IDs currently in the central registry."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{CENTRAL_REGISTRY_URL}/shell-descriptors",
                        headers=headers, timeout=10)
    resp.raise_for_status()
    shells = unwrap_baaxyx_envelope(resp.json())
    return {s.get("id") for s in shells}


def sync_to_central(shells, token):
    """PUT each shell descriptor to the central registry. Remove stale entries."""
    headers = {"Authorization": f"Bearer {token}"}
    synced = 0
    central_ids = get_central_shell_ids(token)
    local_ids = set()

    for shell in shells:
        shell_id = shell.get("id", "")
        if not shell_id:
            continue
        local_ids.add(shell_id)
        encoded_id = b64url_encode(shell_id)
        url = f"{CENTRAL_REGISTRY_URL}/shell-descriptors/{encoded_id}"
        resp = requests.put(url, json=shell, headers=headers, timeout=10)
        if resp.status_code in (200, 201, 204):
            synced += 1
        else:
            print(f"  [WARN] Failed to sync {shell_id}: {resp.status_code}")

    stale_ids = central_ids - local_ids
    for stale_id in stale_ids:
        encoded_id = b64url_encode(stale_id)
        url = f"{CENTRAL_REGISTRY_URL}/shell-descriptors/{encoded_id}"
        resp = requests.delete(url, headers=headers, timeout=10)
        if resp.status_code in (200, 204):
            print(f"  [CLEANUP] Removed stale shell: {stale_id}")

    return synced


def main():
    print(f"[heartbeat] Starting heartbeat service")
    print(f"  Local registry:  {LOCAL_REGISTRY_URL}")
    print(f"  Central registry: {CENTRAL_REGISTRY_URL}")
    print(f"  Public IP:        {MY_PUBLIC_IP}:{MY_PORT}")
    print(f"  Interval:         {HEARTBEAT_INTERVAL}s")

    while True:
        try:
            token = get_jwt_token()
            shells = get_local_shells()
            shells = transform_endpoints(shells)
            synced = sync_to_central(shells, token)
            print(f"  [OK] Synced {synced}/{len(shells)} shells")
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)

        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
```

**`universal-aas/heartbeat/config.py`:**

```python
import os

CENTRAL_REGISTRY_URL = os.getenv("CENTRAL_REGISTRY_URL", "http://192.168.56.212:8085")
LOCAL_REGISTRY_URL = os.getenv("LOCAL_REGISTRY_URL", "http://localhost:8083")
MY_PUBLIC_IP = os.getenv("MY_PUBLIC_IP", "192.168.56.213")
MY_PORT = int(os.getenv("MY_PORT", "8081"))
MY_WEB_UI_URL = os.getenv("MY_WEB_UI_URL", f"https://{MY_PUBLIC_IP}:8443")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://192.168.56.212:9443")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "heartbeat-registry")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "heartbeat-secret-change-me")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "BaSyx")
```

**`universal-aas/heartbeat/requirements.txt`:**

```
requests>=2.31.0
```

**`universal-aas/heartbeat/Dockerfile`:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY heartbeat.py config.py ./
CMD ["python", "-u", "heartbeat.py"]
```

---

## 11. Discovery UI — Implementation

### 11.1 Flask Backend

**`discovery-ui/app.py`:**

```python
#!/usr/bin/env python3
"""Universal AAS Discovery UI — lightweight dashboard for browsing
all registered AAS across the distributed system."""

import os
import requests
from flask import Flask, render_template, jsonify
from urllib.parse import urlparse

app = Flask(__name__)
CENTRAL_REGISTRY_URL = os.getenv("CENTRAL_REGISTRY_URL", "http://central-registry:8080")


def fetch_shells():
    """Fetch shell descriptors from the central registry, unwrapping the BaSyx envelope."""
    resp = requests.get(f"{CENTRAL_REGISTRY_URL}/shell-descriptors", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data if isinstance(data, list) else []


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/shells")
def api_shells():
    """Proxy to central registry, return all shell descriptors."""
    try:
        shells = fetch_shells()
        return jsonify(shells)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/servers")
def api_servers():
    """Aggregate shells by server IP, return server summaries."""
    try:
        shells = fetch_shells()
        servers = {}
        for shell in shells:
            for ep in shell.get("endpoints", []):
                proto_info = ep.get("protocolInformation", {})
                href = proto_info.get("href", "")
                if href:
                    parsed = urlparse(href)
                    ip = parsed.hostname or "unknown"
                    port = parsed.port or 8081
                else:
                    ip = ep.get("host", "unknown")
                    port = ep.get("port", 8081)
                if ip not in servers:
                    servers[ip] = {
                        "ip": ip,
                        "port": port,
                        "protocol": proto_info.get("endpointProtocol", "https"),
                        "shell_count": 0,
                        "shells": [],
                    }
                servers[ip]["shell_count"] += 1
                servers[ip]["shells"].append(shell.get("idShort", shell.get("id", "")))
        return jsonify(list(servers.values()))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/health/<ip>")
def api_health(ip):
    """Check if a remote AAS server is reachable."""
    try:
        resp = requests.get(f"http://{ip}:8081/shells", timeout=5)
        return jsonify({"ip": ip, "reachable": resp.status_code == 200})
    except Exception:
        return jsonify({"ip": ip, "reachable": False})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001, debug=False)
```

### 11.2 HTML Template

**`discovery-ui/templates/index.html`:**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universal AAS Discovery</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header>
        <h1>Universal AAS Discovery</h1>
        <div class="stats">
            <span id="shell-count">0 Products</span>
            <span id="server-count">0 Servers</span>
        </div>
    </header>

    <main>
        <div class="search-bar">
            <input type="text" id="search" placeholder="Search by name, ID, or server IP...">
        </div>

        <div class="content">
            <section class="products">
                <h2>Products</h2>
                <div id="product-list" class="card-grid"></div>
            </section>

            <section class="servers">
                <h2>Servers</h2>
                <div id="server-list" class="card-grid"></div>
            </section>
        </div>
    </main>

    <script src="/static/app.js"></script>
</body>
</html>
```

### 11.3 JavaScript

**`discovery-ui/static/app.js`:**

```javascript
const API_SHELLS = "/api/shells";
const API_SERVERS = "/api/servers";

let allShells = [];
let allServers = [];

async function loadData() {
    const [shellsRes, serversRes] = await Promise.all([
        fetch(API_SHELLS),
        fetch(API_SERVERS),
    ]);
    allShells = await shellsRes.json();
    allServers = await serversRes.json();
    document.getElementById("shell-count").textContent = `${allShells.length} Products`;
    document.getElementById("server-count").textContent = `${allServers.length} Servers`;
    renderShells(allShells);
    renderServers(allServers);
}

function parseHref(ep) {
    const proto_info = ep.protocolInformation || {};
    const href = proto_info.href || "";
    if (href) {
        try {
            const url = new URL(href);
            return { host: url.hostname, port: url.port || 8081, protocol: proto_info.endpointProtocol || "https" };
        } catch {}
    }
    return { host: ep.host || "unknown", port: ep.port || 8081, protocol: ep.protocol || "https" };
}

function renderShells(shells) {
    const container = document.getElementById("product-list");
    container.innerHTML = shells.map(shell => {
        const ep = (shell.endpoints || [])[0] || {};
        const { host, port } = parseHref(ep);
        return `
            <div class="card">
                <h3>${shell.idShort || shell.id}</h3>
                <p class="meta">ID: ${shell.id}</p>
                <p class="meta">Server: ${host}:${port}</p>
                <div class="card-actions">
                    <a href="https://${host}:8443" target="_blank" class="btn">View on Server</a>
                    <a href="${host}:${port}/shells/${encodeURIComponent(shell.id)}" target="_blank" class="btn btn-secondary">Raw API</a>
                </div>
            </div>
        `;
    }).join("");
}

function renderServers(servers) {
    const container = document.getElementById("server-list");
    container.innerHTML = servers.map(s => `
        <div class="card">
            <h3>${s.ip}</h3>
            <p class="meta">${s.shell_count} AAS registered</p>
            <p class="meta">${s.protocol}://${s.ip}:${s.port}</p>
            <div class="card-actions">
                <a href="https://${s.ip}:8443" target="_blank" class="btn">Open Server UI</a>
            </div>
        </div>
    `).join("");
}

document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = allShells.filter(s =>
        (s.idShort || "").toLowerCase().includes(q) ||
        (s.id || "").toLowerCase().includes(q) ||
        JSON.stringify(s.endpoints || []).toLowerCase().includes(q)
    );
    renderShells(filtered);
});

loadData();
setInterval(loadData, 30000); // refresh every 30s
```

### 11.4 CSS

**`discovery-ui/static/style.css`:**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f7fa;
    color: #1a1a2e;
}

header {
    background: #16213e;
    color: white;
    padding: 1.5rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

header h1 { font-size: 1.5rem; }

.stats span {
    background: #0f3460;
    padding: 0.4rem 1rem;
    border-radius: 20px;
    margin-left: 0.5rem;
    font-size: 0.9rem;
}

main { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }

.search-bar { margin-bottom: 2rem; }

.search-bar input {
    width: 100%;
    padding: 0.8rem 1.2rem;
    border: 2px solid #ddd;
    border-radius: 8px;
    font-size: 1rem;
    outline: none;
}

.search-bar input:focus { border-color: #0f3460; }

.content { display: grid; grid-template-columns: 2fr 1fr; gap: 2rem; }

section h2 {
    margin-bottom: 1rem;
    font-size: 1.2rem;
    color: #16213e;
}

.card-grid { display: flex; flex-direction: column; gap: 0.75rem; }

.card {
    background: white;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.card h3 { font-size: 1rem; margin-bottom: 0.3rem; color: #0f3460; }
.card .meta { font-size: 0.85rem; color: #666; margin-bottom: 0.2rem; }

.card-actions { margin-top: 0.6rem; display: flex; gap: 0.5rem; }

.btn {
    display: inline-block;
    padding: 0.4rem 0.8rem;
    background: #0f3460;
    color: white;
    text-decoration: none;
    border-radius: 4px;
    font-size: 0.85rem;
}

.btn:hover { background: #16213e; }
.btn-secondary { background: #e0e0e0; color: #333; }
.btn-secondary:hover { background: #ccc; }

@media (max-width: 768px) {
    .content { grid-template-columns: 1fr; }
}
```

### 11.5 Dockerfile and Requirements

**`discovery-ui/Dockerfile`:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

**`discovery-ui/requirements.txt`:**

```
flask>=3.0.0
requests>=2.31.0
```

---

## 12. Deployment Instructions

### Step 1: Prepare the central stack

```bash
cd /Users/Aziz/Downloads/basyx-setup

# Create directories
mkdir -p universal-aas/heartbeat
mkdir -p discovery-ui/templates
mkdir -p discovery-ui/static

# Create all files from Section 4-11 above
```

### Step 2: Update Keycloak realm

Add the `heartbeat-registry` client, `registry-writer` role, and per-machine
heartbeat users to `keycloak/realm-export.json`.

**Important:** Since the realm is only imported on first start, you must either:
- Delete the Keycloak volume and restart (loses existing data), OR
- Manually add the client/role/user via the Keycloak admin console at
  `https://192.168.56.212:9443/admin`

Recommended: use the admin console to avoid data loss.

### Step 3: Update nginx

Add the `/universal/` location block to `nginx/nginx.conf` inside the
`server { listen 8443 ssl; }` block, before the catch-all `location /` block.

### Step 4: Update existing docker-compose.yml

Add the `basyx-shared` network to `aas-environment` and `aas-registry` services
so the central registry can reach MongoDB and Keycloak through the shared network.

### Step 5: Start the central stack

```bash
cd /Users/Aziz/Downloads/basyx-setup/universal-aas
podman compose up -d
```

### Step 6: Deploy heartbeat on remote machines

```bash
# On machine B (192.168.56.213):
scp -r universal-aas/heartbeat user@192.168.56.213:/opt/heartbeat

# SSH into machine B
ssh user@192.168.56.213

# Set environment variables
export CENTRAL_REGISTRY_URL=http://192.168.56.212:8085
export LOCAL_REGISTRY_URL=http://localhost:8083
export MY_PUBLIC_IP=192.168.56.213
export MY_PORT=8081
export KEYCLOAK_CLIENT_ID=heartbeat-registry
export KEYCLOAK_CLIENT_SECRET=heartbeat-secret-change-me

# Run the heartbeat
cd /opt/heartbeat
pip install -r requirements.txt
python heartbeat.py
```

Or run as a Docker container:

```bash
docker run -d --name heartbeat \
  -e CENTRAL_REGISTRY_URL=http://192.168.56.212:8085 \
  -e LOCAL_REGISTRY_URL=http://localhost:8083 \
  -e MY_PUBLIC_IP=192.168.56.213 \
  -e KEYCLOAK_CLIENT_SECRET=heartbeat-secret-change-me \
  --network host \
  heartbeat-service:latest
```

### Step 7: Verify

```bash
# Check central registry has shells
curl http://192.168.56.212:8085/registry/shell-descriptors

# Open discovery UI
open https://192.168.56.212:8443/universal/
```

---

## 13. Port Map

| Port | Service | Stack | Purpose |
|------|---------|-------|---------|
| 80 | nginx HTTP redirect | Existing | Redirects to :8443 |
| 8081 | AAS Environment | Existing | REST API (local) |
| 8083 | AAS Registry | Existing | Local registry |
| **8085** | **Central AAS Registry** | **Universal** | **Discovery registry** |
| 8443 | nginx HTTPS | Existing | UI + API + `/universal/` |
| 9443 | nginx HTTPS | Existing | Keycloak |
| **3001** | **Discovery UI** | **Universal** | **Dashboard (internal)** |

---

## 14. Key Design Decisions

1. **Separate compose file** — The universal stack is deployed independently
   from existing stacks. This avoids disrupting existing infrastructure and
   allows incremental adoption.

2. **Reuses shared network** — The `basyx-shared` Docker network allows the
   central registry to connect to the existing MongoDB and Keycloak without
   duplicating them.

3. **Shell descriptors only** — The central registry stores metadata, not
   actual AAS data. This keeps it lightweight and avoids data synchronization
   complexity.

4. **Heartbeat over push** — The heartbeat pattern is simpler than a webhook
   approach and handles network partitions gracefully (stale entries show
   "last seen" timestamp).

5. **Shared Keycloak** — Single sign-on across all instances. The heartbeat
   service uses client credentials (no browser interaction needed).

6. **Custom UI over AAS GUI** — The existing AAS Web UI is designed for
   managing a single AAS Environment. The discovery UI provides a cross-server
   view that the standard GUI cannot.

---

## 15. Future Improvements

- **Health monitoring**: Background task that pings each remote server and
  updates online/offline status in the dashboard
- **Submodel preview**: Fetch and display submodel summaries without leaving
  the discovery UI (read-only proxy)
- **Server registration API**: Allow remote servers to self-register via a
  REST endpoint instead of requiring pre-configured Keycloak credentials
- **WebSocket live updates**: Push shell descriptor changes to the UI in
  real-time instead of polling every 30s
- **Multi-LAN support**: Extend heartbeat to work across network segments
  with VPN/tunnel configuration
