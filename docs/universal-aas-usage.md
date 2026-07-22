# Universal AAS — Usage & Testing Guide

> Prerequisite: The main BaSyx stack and the universal stack must both be running.

---

## 1. What the Universal AAS Does

### Working Now

| Feature | Description |
|---|---|
| **Discovery Dashboard** | Browse all registered AAS products across all servers at `https://192.168.56.212:8443/universal/` |
| **Product Search** | Filter products by name, AAS ID, or server IP |
| **Server Overview** | See all registered servers and how many AAS each hosts |
| **Direct Links** | Click "View on server" to jump to the actual server's AAS Web UI |
| **Raw API Links** | Click "Raw API" to get the REST endpoint for any shell |
| **Auto-Refresh** | Dashboard polls the central registry every 30 seconds |
| **Central Registry** | Stores shell descriptors from all servers at `http://192.168.56.212:8085/shell-descriptors` |

### Not Yet Wired

| Feature | Status |
|---|---|
| Heartbeat auto-registration | Script is built but needs to be deployed to remote machines |
| Server health monitoring | API exists (`/api/health/<ip>`) but not shown in UI yet |
| Stale entry cleanup | Handled by the heartbeat but requires it to be running |

---

## 2. Start the Stacks

### Start the main BaSyx stack

```bash
cd /Users/Aziz/Downloads/basyx-setup
podman compose --env-file .env up -d
```

### Start the universal stack

```bash
cd /Users/Aziz/Downloads/basyx-setup/universal-aas
podman compose --env-file ../.env up -d
```

### Verify everything is running

```bash
podman ps --format "table {{.Names}}\t{{.Status}}"
```

Expected containers:

| Container | Status |
|---|---|
| `mongo` | Running (healthy) |
| `keycloak-db` | Running (healthy) |
| `keycloak` | Running (healthy) |
| `aas-environment` | Running |
| `aas-registry` | Running |
| `aas-web-ui` | Running |
| `nginx` | Running |
| `central-registry` | Running |
| `discovery-ui` | Running |

---

## 3. Test from the Host Machine (192.168.56.212)

### Open the dashboard

```
https://192.168.56.212:8443/universal/
```

Accept the self-signed certificate warning.

### Test the API endpoints

```bash
# List all shell descriptors in the central registry
curl http://192.168.56.212:8085/shell-descriptors

# List all shells via the discovery UI API
curl -k https://192.168.56.212:8443/universal/api/shells

# List all servers with product counts
curl -k https://192.168.56.212:8443/universal/api/servers
```

---

## 4. Test from a Remote Machine

### Step 1 — Verify the central registry is reachable

From any machine on the LAN (e.g., 192.168.56.213):

```bash
curl http://192.168.56.212:8085/shell-descriptors
```

Expected (empty until something is registered):

```json
{"paging_metadata":{},"result":[]}
```

### Step 2 — Verify the dashboard is accessible

Open in a browser on any machine in the LAN:

```
https://192.168.56.212:8443/universal/
```

Accept the self-signed certificate warning.

### Step 3 — Manually register a product from a remote machine

This tests the full flow without the heartbeat.

**Important:** BaSyx v3 requires shell descriptor IDs to be **Base64-URL encoded** (not standard URL-encoded) in the path. Use this to encode:

```bash
# Encode an AAS ID to Base64-URL:
python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://admin-shell.io/idta/aas/TechnicalData/2/0').decode())"
# Output: aHR0cHM6Ly9hZG1pbi1zaGVsbC5pby9pZHRhL2Fhcy9UZWNobmljYWxEYXRhLzIvMA
```

Register from machine B (192.168.56.213):

```bash
# First, encode the AAS ID:
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://admin-shell.io/idta/aas/TechnicalData/2/0').decode())")

# Then PUT with Base64-URL encoded ID in the path:
curl -X PUT \
  "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://admin-shell.io/idta/aas/TechnicalData/2/0",
    "idShort": "ProductB_TechData",
    "endpoints": [{
      "interface": "AAS-3.0",
      "protocolInformation": {
        "href": "http://192.168.56.213:8081/shells/aHR0cHM6Ly9hZG1pbi1zaGVsbC5pby9pZHRhL2Fhcy9UZWNobmljYWxEYXRhLzIvMA",
        "endpointProtocol": "http"
      }
    }]
  }'
```

Expected: `HTTP 204 No Content` on success.

Then refresh the dashboard — you should see the new product with a link pointing to `192.168.56.213`.

### Step 4 — Verify registration

```bash
# Check the central registry now has the shell:
curl http://192.168.56.212:8085/shell-descriptors

# Check the dashboard API:
curl -k https://192.168.56.212:8443/universal/api/shells

# Check the server aggregation:
curl -k https://192.168.56.212:8443/universal/api/servers
```

---

## 5. Deploy the Heartbeat (Automatic Registration)

The heartbeat script runs on each remote machine and automatically syncs local
shell descriptors to the central registry every 30 seconds.

### Step 1 — Copy the heartbeat to the remote machine

```bash
scp -r /Users/Aziz/Downloads/basyx-setup/universal-aas/heartbeat \
  user@192.168.56.213:/opt/heartbeat
```

### Step 2 — Install dependencies

```bash
ssh user@192.168.56.213
cd /opt/heartbeat
pip install -r requirements.txt
```

### Step 3 — Set environment variables

```bash
export CENTRAL_REGISTRY_URL=http://192.168.56.212:8085
export LOCAL_REGISTRY_URL=http://localhost:8083
export MY_PUBLIC_IP=192.168.56.213
export MY_PORT=8081
export KEYCLOAK_URL=https://192.168.56.212:9443
export KEYCLOAK_CLIENT_ID=heartbeat-registry
export KEYCLOAK_CLIENT_SECRET=heartbeat-secret-change-me
```

### Step 4 — Run the heartbeat

```bash
python3 heartbeat.py
```

Expected output:

```
[heartbeat] Starting Universal AAS heartbeat service
  Local registry:   http://localhost:8083
  Central registry:  http://192.168.56.212:8085
  Public IP:         192.168.56.213:8081
  Web UI URL:        https://192.168.56.213:8443
  Interval:          30s
  Keycloak:          https://192.168.56.212:9443/realms/BaSyx

  [2026-07-21 14:30:00] Synced 5/5 shells to central registry
  [2026-07-21 14:30:30] Synced 5/5 shells to central registry
```

### Step 5 — Run as a background service (optional)

```bash
# Using nohup:
nohup python3 heartbeat.py > /var/log/heartbeat.log 2>&1 &

# Using systemd (create /etc/systemd/system/aas-heartbeat.service):
[Unit]
Description=AAS Heartbeat - Universal Registry Sync
After=network.target

[Service]
Type=simple
Environment=CENTRAL_REGISTRY_URL=http://192.168.56.212:8085
Environment=LOCAL_REGISTRY_URL=http://localhost:8083
Environment=MY_PUBLIC_IP=192.168.56.213
Environment=MY_PORT=8081
Environment=KEYCLOAK_URL=https://192.168.56.212:9443
Environment=KEYCLOAK_CLIENT_ID=heartbeat-registry
Environment=KEYCLOAK_CLIENT_SECRET=heartbeat-secret-change-me
ExecStart=/usr/bin/python3 /opt/heartbeat/heartbeat.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# Then:
sudo systemctl enable --now aas-heartbeat
```

---

## 6. Run Heartbeat as a Docker Container (Alternative)

```bash
docker run -d \
  --name aas-heartbeat \
  --network host \
  -e CENTRAL_REGISTRY_URL=http://192.168.56.212:8085 \
  -e LOCAL_REGISTRY_URL=http://localhost:8083 \
  -e MY_PUBLIC_IP=192.168.56.213 \
  -e MY_PORT=8081 \
  -e KEYCLOAK_URL=https://192.168.56.212:9443 \
  -e KEYCLOAK_CLIENT_ID=heartbeat-registry \
  -e KEYCLOAK_CLIENT_SECRET=heartbeat-secret-change-me \
  --restart unless-stopped \
  localhost/heartbeat:latest
```

Build the image first:

```bash
cd /Users/Aziz/Downloads/basyx-setup/universal-aas/heartbeat
podman build -t localhost/heartbeat:latest .
```

---

## 7. Troubleshooting

### Dashboard shows "Failed to connect to discovery API"

- Check the universal stack is running: `podman ps | grep -E "central-registry|discovery"`
- Check discovery-ui logs: `podman logs discovery-ui`
- Check central-registry logs: `podman logs central-registry`

### Dashboard shows 0 products

- The central registry is empty — register products via the heartbeat or manually
- Test: `curl http://192.168.56.212:8085/shell-descriptors`

### Heartbeat fails with 401 Unauthorized

- The Keycloak client secret is wrong — check `KEYCLOAK_CLIENT_SECRET`
- The `heartbeat-registry` client may not exist in Keycloak yet — add it via the admin console at `https://192.168.56.212:9443/admin`

### Heartbeat fails with connection error

- Check that the central registry is reachable: `curl http://192.168.56.212:8085/shell-descriptors`
- Check firewall rules — port 8085 must be open on the central machine

### nginx returns 502 for /universal/

- The discovery-ui container may not be running: `podman logs discovery-ui`
- Restart the universal stack: `cd universal-aas && podman compose --env-file ../.env up -d`

### Heartbeat fails with 400 Bad Request on PUT

- The AAS ID must be **Base64-URL encoded** in the path, not standard URL-encoded
- Use `python3 -c "import base64; print(base64.urlsafe_b64encode(b'<aas-id>').decode())"` to encode
- Example: `https://admin-shell.io/idta/aas/Test/1/0` → `aHR0cHM6Ly9hZG1pbi1zaGVsbC5pby9pZHRhL2Fhcy9UZXN0LzEvMA`

### Shell descriptors have "unknown" IP in the server list

- The local AAS registry uses BaSyx v3's `protocolInformation` format
- The heartbeat transforms `localhost`/`0.0.0.0` endpoints to the configured `MY_PUBLIC_IP`
- Ensure `MY_PUBLIC_IP` is set correctly when running the heartbeat

---

## 8. Port Reference

| Port | Service | Access |
|---|---|---|
| 8443 | nginx (HTTPS) | Dashboard at `/universal/`, API at `/universal/api/*` |
| 8085 | Central Registry | Direct REST API: `/shell-descriptors` |
| 8081 | AAS Environment (local) | Local AAS REST API |
| 8083 | AAS Registry (local) | Local registry REST API |
| 9443 | Keycloak (HTTPS) | Auth for heartbeat services |

---

## 9. API Reference

### GET /universal/api/shells

Returns all shell descriptors from the central registry.

```bash
curl -k https://192.168.56.212:8443/universal/api/shells
```

Response:

```json
[
  {
    "id": "https://admin-shell.io/idta/aas/TechnicalData/2/0",
    "idShort": "ProductB_TechData",
    "endpoints": [
      {
        "interface": "AAS-3.0",
        "protocolInformation": {
          "href": "http://192.168.56.213:8081/shells/...",
          "endpointProtocol": "http"
        }
      }
    ]
  }
]
```

### GET /universal/api/servers

Returns all registered servers with product counts.

```bash
curl -k https://192.168.56.212:8443/universal/api/servers
```

Response:

```json
[
  {
    "ip": "192.168.56.213",
    "port": 8081,
    "protocol": "https",
    "shell_count": 5,
    "shells": ["ProductA", "ProductB", "ProductC"]
  }
]
```

### GET /universal/api/health/:ip

Check if a remote AAS server is reachable.

```bash
curl -k https://192.168.56.212:8443/universal/api/health/192.168.56.213
```

Response:

```json
{"ip": "192.168.56.213", "reachable": true}
```

### Direct Central Registry API

```bash
# Encode an AAS ID for use in URL paths:
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://admin-shell.io/idta/aas/TechnicalData/2/0').decode())")

# List all shell descriptors
curl http://192.168.56.212:8085/shell-descriptors

# Get a specific shell (use Base64-URL encoded ID)
curl "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}"

# Register/update a shell (PUT with Base64-URL encoded ID)
curl -X PUT "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" \
  -H "Content-Type: application/json" \
  -d '{ ... }'

# Delete a shell (DELETE with Base64-URL encoded ID)
curl -X DELETE "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}"
```
