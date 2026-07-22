# Universal AAS — Testing Instructions

> Run all tests from the host machine (192.168.56.212) unless noted otherwise.

---

## Prerequisites

```bash
cd /Users/Aziz/Downloads/basyx-setup

# Verify both stacks are running
podman ps --format "table {{.Names}}\t{{.Status}}" | grep -E "central-registry|discovery-ui|nginx|mongo|keycloak"
```

Expected: all containers show `Up` or `Up (healthy)`.

---

## 1. Central Registry API

### 1.1 List all shells (expect 2 existing)

```bash
curl -s http://192.168.56.212:8085/shell-descriptors | python3 -m json.tool
```

Expect: `{"paging_metadata":{},"result":[...]}` with DPP_FIBROTOR and TestProduct entries.

### 1.2 Base64-URL encode a shell ID

```bash
python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://admin-shell.io/idta/aas/TechnicalData/2/0').decode())"
```

Expect: `aHR0cHM6Ly9hZG1pbi1zaGVsbC5pby9pZHRhL2Fhcy9UZWNobmljYWxEYXRhLzIvMA`

### 1.3 GET a specific shell

```bash
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://admin-shell.io/idta/aas/TechnicalData/2/0').decode())")
curl -s "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" | python3 -m json.tool
```

Expect: HTTP 200, full shell descriptor JSON.

### 1.4 PUT a new shell (create)

```bash
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://test.example.com/aas/TestProduct2/1/0').decode())")
curl -s -w "\nHTTP %{http_code}\n" -X PUT \
  "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://test.example.com/aas/TestProduct2/1/0",
    "idShort": "TestProduct2",
    "endpoints": [{
      "interface": "AAS-3.0",
      "protocolInformation": {
        "href": "http://192.168.56.212:8082/shells/test2",
        "endpointProtocol": "http"
      }
    }]
  }'
```

Expect: HTTP 201 Created or 204 No Content.

### 1.5 Verify the new shell exists

```bash
curl -s http://192.168.56.212:8085/shell-descriptors | python3 -c "import sys,json; r=json.load(sys.stdin); [print(s['idShort'], s['id']) for s in r.get('result',r)]"
```

Expect: TestProduct2 appears in the list.

### 1.6 PUT update an existing shell

```bash
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://test.example.com/aas/TestProduct2/1/0').decode())")
curl -s -w "\nHTTP %{http_code}\n" -X PUT \
  "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://test.example.com/aas/TestProduct2/1/0",
    "idShort": "TestProduct2_Updated",
    "endpoints": [{
      "interface": "AAS-3.0",
      "protocolInformation": {
        "href": "http://192.168.56.212:8082/shells/test2",
        "endpointProtocol": "http"
      }
    }]
  }'
```

Expect: HTTP 204 No Content.

### 1.7 Verify update took effect

```bash
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://test.example.com/aas/TestProduct2/1/0').decode())")
curl -s "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" | python3 -m json.tool
```

Expect: `idShort` is now `TestProduct2_Updated`.

### 1.8 DELETE the test shell

```bash
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://test.example.com/aas/TestProduct2/1/0').decode())")
curl -s -w "\nHTTP %{http_code}\n" -X DELETE "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}"
```

Expect: HTTP 204 No Content.

### 1.9 Verify deletion

```bash
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://test.example.com/aas/TestProduct2/1/0').decode())")
curl -s -w "\nHTTP %{http_code}\n" "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}"
```

Expect: HTTP 404 Not Found.

---

## 2. Discovery UI API

### 2.1 Shells endpoint

```bash
curl -sk https://192.168.56.212:8443/universal/api/shells | python3 -m json.tool
```

Expect: JSON array of shell descriptors (unwrapped, no `paging_metadata` envelope).

### 2.2 Servers endpoint

```bash
curl -sk https://192.168.56.212:8443/universal/api/servers | python3 -m json.tool
```

Expect: JSON array of server objects with real IPs (not "unknown"), port numbers, and shell counts.

Example:
```json
[
  {
    "ip": "192.168.56.212",
    "port": 8082,
    "protocol": "http",
    "shell_count": 1,
    "shells": ["DPP_FIBROTOR_ER15_V2"]
  },
  {
    "ip": "192.168.56.213",
    "port": 8081,
    "protocol": "http",
    "shell_count": 1,
    "shells": ["TestProduct"]
  }
]
```

### 2.3 Health check

```bash
curl -sk https://192.168.56.212:8443/universal/api/health/192.168.56.212
```

Expect: `{"ip":"192.168.56.212","reachable":true}`

```bash
curl -sk https://192.168.56.212:8443/universal/api/health/192.168.56.999
```

Expect: `{"ip":"192.168.56.999","reachable":false}`

---

## 3. Discovery Dashboard (Browser)

### 3.1 Open the dashboard

Navigate to: `https://192.168.56.212:8443/universal/`

Accept the self-signed certificate warning.

### 3.2 Verify visual elements

| Check | Expected |
|-------|----------|
| Header shows stats | "X Products" and "Y Servers" |
| Product cards visible | Shell names and IDs displayed |
| Server IPs real | IP addresses (not "unknown") from `protocolInformation.href` |
| "View on Server" link | Opens `https://<ip>:8443` |
| "Raw API" link | Opens the shell's REST endpoint |

### 3.3 Test search

Type a product name or AAS ID into the search box. Verify the list filters correctly.

### 3.4 Test auto-refresh

Wait 30 seconds. Verify the dashboard refreshes automatically (product/server counts may update).

---

## 4. Heartbeat Service

### 4.1 Unit test the helpers

```bash
cd /Users/Aziz/Downloads/basyx-setup/universal-aas/heartbeat
python3 -c "
import base64
from urllib.parse import urlparse

# Test b64url_encode
def b64url_encode(v):
    return base64.urlsafe_b64encode(v.encode()).decode()

aid = 'https://admin-shell.io/idta/aas/TechnicalData/2/0'
encoded = b64url_encode(aid)
decoded = base64.urlsafe_b64decode(encoded).decode()
assert decoded == aid, f'Mismatch: {decoded} != {aid}'
print(f'b64url_encode OK: {aid} -> {encoded} -> {decoded}')

# Test unwrap_baaxyx_envelope
def unwrap(data):
    if isinstance(data, dict) and 'result' in data:
        return data['result']
    return data if isinstance(data, list) else []

env = {'paging_metadata': {}, 'result': [{'id': 'a'}, {'id': 'b'}]}
assert len(unwrap(env)) == 2
assert unwrap([]) == []
assert unwrap({'key': 'val'}) == []
print('unwrap_baaxyx_envelope OK')

# Test URL parsing
href = 'http://192.168.56.213:8081/shells/test'
p = urlparse(href)
assert p.hostname == '192.168.56.213'
assert p.port == 8081
print(f'URL parsing OK: {p.hostname}:{p.port}')
"
```

Expect: all assertions pass, 3 OK messages printed.

### 4.2 Integration test (dry run against central registry)

```bash
cd /Users/Aziz/Downloads/basyx-setup/universal-aas/heartbeat
CENTRAL_REGISTRY_URL=http://192.168.56.212:8085 python3 -c "
import base64, requests
from urllib.parse import urlparse

url = 'http://192.168.56.212:8085/shell-descriptors'
resp = requests.get(url, timeout=10)
data = resp.json()
shells = data.get('result', data) if isinstance(data, dict) else data
print(f'Found {len(shells)} shells in central registry')
for s in shells:
    print(f'  - {s.get(\"idShort\",\"?\")} [{s.get(\"id\",\"?\")}]')
    for ep in s.get('endpoints', []):
        pi = ep.get('protocolInformation', {})
        href = pi.get('href', '')
        if href:
            p = urlparse(href)
            print(f'    endpoint: {p.hostname}:{p.port}')
"
```

Expect: lists all shells with their real IPs parsed from `protocolInformation.href`.

### 4.3 Test PUT via heartbeat encoding

```bash
cd /Users/Aziz/Downloads/basyx-setup/universal-aas/heartbeat
python3 -c "
import base64, requests

def b64url_encode(v):
    return base64.urlsafe_b64encode(v.encode()).decode()

shell = {
    'id': 'https://test.example.com/aas/HeartbeatTest/1/0',
    'idShort': 'HeartbeatTest',
    'endpoints': [{
        'interface': 'AAS-3.0',
        'protocolInformation': {
            'href': 'http://192.168.56.212:8082/shells/hbtest',
            'endpointProtocol': 'http'
        }
    }]
}

encoded_id = b64url_encode(shell['id'])
url = f'http://192.168.56.212:8085/shell-descriptors/{encoded_id}'
resp = requests.put(url, json=shell, timeout=10)
print(f'PUT {resp.status_code}: {resp.text[:100]}')

# Verify
resp2 = requests.get(url, timeout=10)
print(f'GET {resp2.status_code}: idShort={resp2.json().get(\"idShort\")}')

# Cleanup
resp3 = requests.delete(url, timeout=10)
print(f'DELETE {resp3.status_code}')
"
```

Expect: PUT 201/204, GET 200, DELETE 204.

---

## 5. nginx Proxy

### 5.1 Dashboard HTML loads

```bash
curl -sk -o /dev/null -w "HTTP %{http_code}, size: %{size_download} bytes\n" \
  https://192.168.56.212:8443/universal/
```

Expect: HTTP 200, size > 1000 bytes.

### 5.2 Static assets load

```bash
curl -sk -o /dev/null -w "HTTP %{http_code}\n" https://192.168.56.212:8443/universal/static/style.css
curl -sk -o /dev/null -w "HTTP %{http_code}\n" https://192.168.56.212:8443/universal/static/app.js
```

Expect: both return HTTP 200.

### 5.3 API proxied correctly

```bash
curl -sk -o /dev/null -w "HTTP %{http_code}\n" https://192.168.56.212:8443/universal/api/shells
```

Expect: HTTP 200.

---

## 6. Full Round-Trip Test

This tests the complete flow: register a shell via the registry API, verify it shows in the dashboard, then clean up.

```bash
echo "=== Step 1: Register test shell ==="
ENCODED_ID=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://test.example.com/aas/RoundTrip/1/0').decode())")
curl -s -w "\nHTTP %{http_code}\n" -X PUT \
  "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://test.example.com/aas/RoundTrip/1/0",
    "idShort": "RoundTripTest",
    "endpoints": [{
      "interface": "AAS-3.0",
      "protocolInformation": {
        "href": "http://192.168.56.212:8082/shells/roundtrip",
        "endpointProtocol": "http"
      }
    }]
  }'

echo ""
echo "=== Step 2: Verify in discovery API ==="
curl -sk https://192.168.56.212:8443/universal/api/shells | python3 -c "
import sys, json
shells = json.load(sys.stdin)
found = [s for s in shells if 'RoundTrip' in s.get('idShort','')]
print(f'Found {len(found)} RoundTrip shells')
for s in found:
    print(f'  {s[\"idShort\"]} at {s[\"endpoints\"][0][\"protocolInformation\"][\"href\"]}')
"

echo ""
echo "=== Step 3: Check server aggregation ==="
curl -sk https://192.168.56.212:8443/universal/api/servers | python3 -c "
import sys, json
servers = json.load(sys.stdin)
for s in servers:
    print(f'  {s[\"ip\"]}:{s[\"port\"]} - {s[\"shell_count\"]} shells')
"

echo ""
echo "=== Step 4: Cleanup ==="
curl -s -w "DELETE HTTP %{http_code}\n" -X DELETE "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}"

echo ""
echo "=== Step 5: Verify removal ==="
curl -s -w "GET HTTP %{http_code}\n" "http://192.168.56.212:8085/shell-descriptors/${ENCODED_ID}"
```

Expected output:
```
=== Step 1: Register test shell ===
HTTP 201

=== Step 2: Verify in discovery API ===
Found 1 RoundTrip shells
  RoundTripTest at http://192.168.56.212:8082/shells/roundtrip

=== Step 3: Check server aggregation ===
  192.168.56.212:8082 - 2 shells
  192.168.56.213:8081 - 1 shells

=== Step 4: Cleanup ===
DELETE HTTP 204

=== Step 5: Verify removal ===
GET HTTP 404
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| PUT returns 400 | AAS ID must be Base64-URL encoded, not percent-encoded |
| PUT returns 500 | Check JSON body is valid; check central registry logs: `podman logs central-registry` |
| Dashboard shows "unknown" IP | Shell endpoints use old format; heartbeat must re-register with `protocolInformation` format |
| Dashboard shows 0 products | Central registry empty; check `curl http://192.168.56.212:8085/shell-descriptors` |
| 502 from `/universal/` | Discovery UI container down; check `podman logs discovery-ui` |
| Heartbeat 401 | Keycloak `heartbeat-registry` client missing or secret wrong |
| Heartbeat connection error | Central registry unreachable; check port 8085 is open |
