# Universal AAS — Upload Flow Guide

> How AAS data flows through the distributed system.
>
> **Key principle:** The Universal AAS Registry stores **metadata only** (shell descriptors).
> Actual AAS data (submodels, concept descriptions) stays on the machine that owns it.

---

## What Goes Where

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL MACHINE (e.g., 192.168.56.213)                      │
│                                                             │
│  AAS Environment (:8081)                                    │
│  ├── Stores FULL AAS data (submodels, files, blobs)        │
│  └── Created from uploaded .aasx / .json file              │
│                                                             │
│  AAS Registry (:8083)                                       │
│  └── Stores shell descriptor (metadata/pointer only)       │
│      ├── AAS ID                                            │
│      ├── Short name                                        │
│      └── Endpoint URL → points back to :8081               │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ heartbeat syncs (metadata only)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  UNIVERSAL / CENTRAL REGISTRY (:8085)                       │
│                                                             │
│  Stores ONLY shell descriptors from ALL machines:           │
│  ├── Machine A's shells (metadata)                         │
│  ├── Machine B's shells (metadata)                         │
│  └── Machine C's shells (metadata)                         │
│                                                             │
│  Does NOT store: submodels, concept descriptions, files    │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ discovery UI reads metadata
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  DISCOVERY UI (/universal/)                                 │
│                                                             │
│  Shows: product names, IDs, which server hosts each        │
│  Links to: actual server for full data access              │
└─────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Flow

### Step 1: Upload AASX to the LOCAL machine

Upload the `.aasx` file to the machine that will **host** the AAS data. This is NOT the universal registry.

```bash
# Example: upload to machine A's AAS Environment
# Option A — via the AAS Web UI at https://192.168.56.212:8443
# Option B — via REST API:
curl -X POST http://192.168.56.212:8081/upload \
  -F "file=@data/product_A.aasx"
```

**What happens:**
- The AAS Environment parses the AASX file (ZIP containing XML)
- Extracts: AAS ID, submodels, property values, files
- Stores the **full AAS data** in its internal MongoDB
- Creates the AAS and submodels via its own API (`POST /shells`, `POST /submodels`)

**Result:** The AAS data now lives on this machine at `:8081`.

### Step 2: Local registry creates a shell descriptor

The AAS Environment automatically notifies the local AAS Registry (`:8083`). The registry creates a **shell descriptor** — a lightweight metadata record:

```json
{
  "id": "https://admin-shell.io/idta/aas/ProductA/1/0",
  "idShort": "ProductA",
  "endpoints": [{
    "interface": "AAS-3.0",
    "protocolInformation": {
      "href": "http://localhost:8082/shells/aHR0cHM6Ly9h...",
      "endpointProtocol": "http"
    }
  }]
}
```

**What this contains:**
- AAS ID (unique identifier)
- Short name (human-readable)
- Endpoint URL (where to find the actual AAS data on this machine)

**What this does NOT contain:**
- Submodel data
- Property values
- Files or blobs
- Concept descriptions

### Step 3: Heartbeat syncs metadata to central registry

The heartbeat service (running on each machine) periodically:
1. Reads shell descriptors from the local registry (`:8083`)
2. Updates the endpoint URLs to use the machine's public IP
3. PUTs each shell descriptor to the central registry (`:8085`)

```bash
# What the heartbeat does every 30 seconds:
GET  http://localhost:8083/shell-descriptors    # read local metadata
PUT  http://192.168.56.212:8085/shell-descriptors/{encoded-id}  # sync to central
```

**The central registry now knows:**
- ProductA exists
- It's hosted on machine 192.168.56.213
- The endpoint URL to reach it

**The central registry does NOT have:**
- The actual AAS data
- Any submodels
- Any property values

### Step 4: Discovery dashboard shows the product

The discovery UI reads shell descriptors from the central registry and displays them. Each product card links to the actual server.

---

## What Is a Shell Descriptor?

A shell descriptor is a **metadata record** — a pointer to where the actual AAS data lives.

| Field | Purpose |
|-------|---------|
| `id` | Unique AAS identifier (e.g., `https://admin-shell.io/idta/aas/ProductA/1/0`) |
| `idShort` | Human-readable name (e.g., `ProductA`) |
| `endpoints[].protocolInformation.href` | URL to the AAS on the hosting server |

Think of it like a business card:
- It tells you **who** the AAS is (ID, name)
- It tells you **where** to find it (endpoint URL)
- It does NOT contain the AAS data itself

---

## What Goes Into the Central Registry

The central registry at `:8085` stores an array of shell descriptors:

```json
{
  "paging_metadata": {},
  "result": [
    {
      "id": "https://admin-shell.io/idta/aas/TechnicalData/2/0",
      "idShort": "DPP_FIBROTOR_ER15_V2",
      "endpoints": [{
        "interface": "AAS-3.0",
        "protocolInformation": {
          "href": "http://192.168.56.212:8082/shells/aHR0cHM6Ly9h...",
          "endpointProtocol": "http"
        }
      }]
    },
    {
      "id": "https://admin-shell.io/idta/aas/ProductA/1/0",
      "idShort": "ProductA",
      "endpoints": [{
        "interface": "AAS-3.0",
        "protocolInformation": {
          "href": "http://192.168.56.213:8081/shells/aHR0cHM6Ly9h...",
          "endpointProtocol": "http"
        }
      }]
    }
  ]
}
```

That's all. No submodels. No property values. No files. Just pointers.

---

## Tools Required

| Tool | Purpose | Where to use |
|------|---------|--------------|
| Web browser | Upload AASX via AAS Web UI | Any machine on the LAN |
| `curl` | Upload AASX via REST API, test registry endpoints | Command line |
| `python3` | Base64-URL encoding for registry API paths | Command line |
| AASX Package Editor / Explorer | Create or edit AASX files | Desktop application |

---

## Practical Examples

### Example 1: Upload an AASX file to a local machine

```bash
# Upload product_A.aasx to machine A's AAS Environment
curl -X POST http://192.168.56.212:8081/upload \
  -F "file=@data/product_A.aasx"

# Verify the shell descriptor was created in the local registry
curl -s http://192.168.56.212:8083/shell-descriptors | python3 -m json.tool

# Wait 30s for heartbeat, then verify it appeared in the central registry
curl -s http://192.168.56.212:8085/shell-descriptors | python3 -m json.tool

# Check the discovery dashboard API
curl -sk https://192.168.56.212:8443/universal/api/shells | python3 -m json.tool
```

### Example 2: Manually register a shell descriptor (metadata only)

When you want to register a product in the discovery system without uploading an AASX file. This creates a pointer in the central registry only.

```bash
# Encode the AAS ID to Base64-URL (required by BaSyx API)
AAS_ID="https://admin-shell.io/idta/aas/ProductA/1/0"
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'${AAS_ID}').decode())")

# PUT the shell descriptor to the central registry
curl -X PUT "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" \
  -H "Content-Type: application/json" \
  -d "{
    \"id\": \"${AAS_ID}\",
    \"idShort\": \"ProductA\",
    \"endpoints\": [{
      \"interface\": \"AAS-3.0\",
      \"protocolInformation\": {
        \"href\": \"http://192.168.56.213:8081/shells/${ENCODED_ID}\",
        \"endpointProtocol\": \"http\"
      }
    }]
  }"

# The product now appears in the discovery dashboard
curl -sk https://192.168.56.212:8443/universal/api/shells | python3 -m json.tool
```

> **Note:** This only registers metadata. Clicking "View on Server" in the dashboard
> will only work if machine `192.168.56.213` actually hosts that AAS.

### Example 3: List all products across all servers

```bash
curl -sk https://192.168.56.212:8443/universal/api/servers | python3 -c "
import sys, json
servers = json.load(sys.stdin)
for s in servers:
    print(f\"{s['ip']}:{s['port']}  ({s['shell_count']} shells)\")
    for name in s['shells']:
        print(f\"  - {name}\")
"
```

---

## Common AAS IDs in This Project

| AAS ID | Source file | Description |
|--------|-------------|-------------|
| `https://admin-shell.io/idta/aas/TechnicalData/2/0` | `data/converted/DPP_FIBROTOR_ER15_V2.aasx` | Digital Product Passport — Technical Data |
| `https://admin-shell.io/idta/aas/ProductA/1/0` | `data/product_A.aasx` | Generic test product |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| AASX upload fails | Check file is valid AASX (ZIP with `aasx/aas.xml` inside) |
| Shell not in central registry | Wait 30s for heartbeat; check heartbeat logs with `podman logs <heartbeat-container>` |
| Dashboard shows "unknown" IP | Shell was registered without proper `protocolInformation.href` |
| Dashboard shows 0 products | Central registry is empty; register shells via heartbeat or manually |
| Heartbeat fails with 401 | Keycloak `heartbeat-registry` client missing or secret wrong |
| PUT returns 400 Bad Request | AAS ID must be Base64-URL encoded, not percent-encoded |
