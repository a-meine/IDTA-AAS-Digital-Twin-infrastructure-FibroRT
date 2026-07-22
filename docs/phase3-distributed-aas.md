# Phase 3 — Distributed AAS Communication (Same Host)

## Architecture

Two independent BaSyx stacks on one machine, sharing a single Keycloak instance.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Shared Docker Network (basyx-shared)                │
│                                                                             │
│  ┌──────────────┐          ┌──────────────┐                                 │
│  │   Team A     │          │   Team B     │                                 │
│  │  nginx:8443  │          │  nginx:8444  │                                 │
│  │  (HTTPS UI)  │          │  (HTTPS UI)  │                                 │
│  └──────┬───────┘          └──────┬───────┘                                 │
│         │                         │                                         │
│  ┌──────┴───────┐          ┌──────┴───────┐                                 │
│  │ aas-env:8081 │          │ aas-env:8082 │                                 │
│  │ (AAS Server) │          │ (AAS Server) │                                 │
│  └──────┬───────┘          └──────┬───────┘                                 │
│         │                         │                                         │
│  ┌──────┴───────┐          ┌──────┴───────┐                                 │
│  │ aas-reg:8083 │          │ aas-reg:8084 │                                 │
│  │ (Registry)   │          │ (Registry)   │                                 │
│  └──────────────┘          └──────────────┘                                 │
│                                                                             │
│                     ┌──────────────────────┐                                │
│                     │   Keycloak:8080      │                                │
│                     │  (Shared JWT Auth)   │                                │
│                     │  KC_HOSTNAME:        │                                │
│                     │  192.168.56.212      │                                │
│                     └──────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────────┘

  Team A (same machine):
    nginx:9443  →  Keycloak (TLS termination)
    AAS Web UI  →  https://192.168.56.212:8443
    Registry    →  http://192.168.56.212:8083

  Team B (same machine):
    AAS Web UI  →  https://localhost:8444
    Registry    →  http://localhost:8084
```

## Why Shared Keycloak (Not Two Separate Keycloaks)

BaSyx Java SDK `jwtBearerTokenProvider` accepts **exactly one issuer**.
Each Keycloak instance generates JWTs with a different `iss` claim —
a server configured to validate Team A's JWTs will reject Team B's JWTs
and vice versa. Two separate Keycloaks would require either:

1. A token exchange proxy that re-signs JWTs (complex, fragile), or
2. Dynamic `issuer-uri` per request (not supported by BaSyx Java SDK)

The shared Keycloak is the only practical solution.

## Limitation: No Registry Federation

BaSyx Java SDK has **no built-in registry federation**. Each registry is
isolated. To query data from another team, you must:

1. **Manually register** the remote team's shell descriptors in your registry
2. **Delegation properties** tell the AAS Environment where to route
   submodel access for remote AAS

## REST API Data Exchange

Since there's no federation, cross-team data exchange uses direct REST calls:

```bash
# Query Team A's shells from Team B's AAS Environment
curl -k https://192.168.56.212:8081/shells \
  -H "Authorization: Bearer <jwt>"

# Register a remote shell descriptor in Team B's registry
curl -X POST http://localhost:8084/registry/shell-descriptors \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://admin-shell.io/idta/aas/ProductA/1/0",
    "idShort": "ProductA",
    "endpoints": [{
      "protocol": "https",
      "host": "192.168.56.212",
      "port": 8081,
      "basePath": "/shells"
    }]
  }'
```

## Delegation Properties

A shell descriptor's `submodelEndpoints` tells the AAS Environment where
to fetch submodel data. When the AAS Environment receives a submodel access
request for a shell it doesn't own, it looks at the `submodelEndpoints` to
route the request to the correct remote server.

Example delegation property in a shell descriptor:

```json
{
  "id": "https://admin-shell.io/idta/aas/ProductA/1/0",
  "submodelEndpoints": [
    {
      "idShort": "TechnicalData",
      "address": "http://aas-environment:8081/submodels"
    }
  ]
}
```

## Setup Instructions

### Step 1: Start Team A's Stack

```bash
cd /Users/Aziz/Downloads/basyx-setup
docker compose up -d
```

Verify Keycloak is accessible:

```bash
# Check Keycloak realm is active
curl -s https://192.168.56.212:9443/realms/BaSyx/.well-known/openid-configuration | head -5
```

### Step 2: Generate Unique AASX Files

```bash
cd /Users/Aziz/Downloads/basyx-setup

# Product A (for Team A)
python3 data/scripts/json_to_aasx.py \
  data/template/TechData_2.0.json \
  data/product_A.aasx \
  --aas-id "https://admin-shell.io/idta/aas/ProductA/1/0" \
  --aas-id-short "ProductA" \
  --submodel-prefix "/aasProductA"

# Product B (for Team B)
python3 data/scripts/json_to_aasx.py \
  data/template/TechData_2.0.json \
  /tmp/product_B.aasx \
  --aas-id "https://admin-shell.io/idta/aas/ProductB/1/0" \
  --aas-id-short "ProductB" \
  --submodel-prefix "/aasProductB"
```

### Step 3: Start Team B's Stack

```bash
cd /Users/Aziz/Downloads/team-B
docker compose up -d
```

Team B's stack connects to Team A's Keycloak through the `basyx-shared`
Docker network.

### Step 4: Register Team B's AAS in Team A's Registry

Since there's no federation, manually register Team B's shell in Team A's
registry so Team A can discover it:

```bash
curl -X POST http://localhost:8083/registry/shell-descriptors \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://admin-shell.io/idta/aas/ProductB/1/0",
    "idShort": "ProductB",
    "endpoints": [{
      "protocol": "https",
      "host": "localhost",
      "port": 8444,
      "basePath": "/shells"
    }]
  }'
```

And vice versa — register Team A's shell in Team B's registry:

```bash
curl -X POST http://localhost:8084/registry/shell-descriptors \
  -H "Content-Type: application/json" \
  -d '{
    "id": "https://admin-shell.io/idta/aas/ProductA/1/0",
    "idShort": "ProductA",
    "endpoints": [{
      "protocol": "https",
      "host": "192.168.56.212",
      "port": 8443,
      "basePath": "/shells"
    }]
  }'
```

### Step 5: Access the Web UIs

| Team | URL | Keycloak |
|------|-----|----------|
| A | https://192.168.56.212:8443 | https://192.168.56.212:9443 |
| B | https://localhost:8444 | https://192.168.56.212:9443 |

Login credentials are the same for both — both UIs redirect to the shared
Keycloak at `192.168.56.212:9443`.

## Port Map

| Port | Service | Stack |
|------|---------|-------|
| 80 | nginx HTTP redirect | Team A |
| 8081 | AAS Environment | Team A |
| 8082 | AAS Environment | Team B |
| 8083 | AAS Registry | Team A |
| 8084 | AAS Registry | Team B |
| 8443 | nginx HTTPS (UI + API) | Team A |
| 8444 | nginx HTTPS (UI + API) | Team B |
| 9443 | nginx HTTPS (Keycloak) | Team A |
