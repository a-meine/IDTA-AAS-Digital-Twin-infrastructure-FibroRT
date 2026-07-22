# BaSyx AAS Setup - Architecture & Authentication Guide

> Machine IP: `192.168.56.212` (defined in `.env` as `HOST_IP`)

---

## Table of Contents

1. [Overview](#overview)
2. [Services & Ports](#services--ports)
3. [Architecture Diagrams](#architecture-diagrams)
4. [Phase 1: Without Reverse Proxy](#phase-1-without-reverse-proxy)
5. [Phase 2: With Reverse Proxy (Current)](#phase-2-with-reverse-proxy-current)
6. [Authentication Flow - Step by Step](#authentication-flow---step-by-step)
7. [Configuration Files Reference](#configuration-files-reference)
8. [Configuration Workflow](#configuration-workflow)
9. [Users & Roles](#users--roles)
10. [RBAC Rules](#rbac-rules)
11. [Troubleshooting](#troubleshooting)

---

## Overview

This setup runs an **Eclipse BaSyx AAS (Asset Administration Shell)** stack using Docker Compose. It consists of 6 containers providing:

- AAS storage and REST API (aas-environment)
- AAS web frontend (aas-gui)
- AAS discovery registry (aas-registry)
- OAuth2 identity provider (Keycloak)
- Database for AAS data (MongoDB)
- Database for Keycloak (PostgreSQL)
- HTTPS reverse proxy (nginx)

---

## Services & Ports

### Exposed Ports (accessible from the network)

| Port  | Protocol | Service               | Accessible From    |
|-------|----------|-----------------------|--------------------|
| 8443  | HTTPS    | AAS Web UI (nginx)    | Any machine        |
| 9443  | HTTPS    | Keycloak (nginx)      | Any machine        |
| 8081  | HTTP     | AAS Environment REST  | Any machine        |
| 8083  | HTTP     | AAS Registry / Swagger| Any machine        |
| 27017 | TCP      | MongoDB               | Localhost only (*) |

> (*) MongoDB port 27017 is mapped but should only be accessed from the Docker host. Restrict in production.

### Internal Docker Network Ports (container-to-container)

| Port  | Service               | Used By                                    |
|-------|-----------------------|--------------------------------------------|
| 8080  | Keycloak (internal)   | nginx, aas-environment, aas-registry       |
| 3000  | AAS Web UI (internal) | nginx                                      |
| 8080  | AAS Registry (internal)| aas-environment                           |
| 5432  | PostgreSQL            | keycloak                                   |
| 27017 | MongoDB               | aas-environment, aas-registry              |

### Port Summary Diagram

```
Network (any machine)              Docker Internal
========================           ========================

:80  ──nginx──> 301 redirect to :8443
:8443 ──nginx──> /shells,/submodels,/concept-descriptions
                    ──> aas-environment:8081
                  /* ──> aas-web-ui:3000
:9443 ──nginx──> keycloak:8080 ──> keycloak-db:5432
:8081 ──────────> aas-environment:8081 ──> mongo:27017
                                        ──> aas-registry:8080
                                        ──> keycloak:8080 (JWT certs)
:8083 ──────────> aas-registry:8080 ──> mongo:27017
                                        ──> keycloak:8080 (JWT certs)
:27017 ─────────> mongo:27017
```

> See [REVERSE-PROXY.md](REVERSE-PROXY.md) for full details on the
> path-based routing and HTTPS configuration.

---

## Architecture Diagrams

### Full System Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │              Docker Host (192.168.56.212)   │
                         │                                             │
  Browser                │  ┌─────────┐                               │
  (any machine)          │  │  nginx   │                               │
      │                  │  │          │    ┌──────────────┐           │
      │  HTTPS :8443     │  │  :8443 ──┼──> │ aas-web-ui   │           │
      │  /shells, etc.   │  │   path   │    │   :3000      │           │
      ├──────────────────┼──┼──────────┤    └──────────────┘           │
      │                  │  │          │    ┌──────────────────┐       │
      │                  │  │   /shells├──> │ aas-environment  │       │
      │                  │  │          │    │     :8081        │       │
      │                  │  │          │    └───────┬──────────┘       │
      │  HTTPS :9443     │  │  :9443 ──┼──> ┌──────┴──────┐           │
      ├──────────────────┼──┼──────────┤    │  Keycloak    │           │
      │                  │  └─────────┘    │   :8080      │           │
      │                  │                 └───────┬──────┘           │
      │  HTTP :8081      │                 ┌───────┴──────┐           │
      ├──────────────────┼────────────────>│ Keycloak-DB  │           │
      │  (REST API)      │                 │ PostgreSQL   │           │
      │                  │                 └──────────────┘           │
      │  HTTP :8083      │                 ┌──────────────┐           │
      ├──────────────────┼────────────────>│ aas-registry │           │
      │  (Swagger)       │                 │   :8080      │           │
      │                  │                 └───────┬──────┘           │
      └──────────────────┘                 ┌───────┴──────┐           │
                                           │    MongoDB   │           │
                                           │   :27017    │           │
                                           └──────────────┘           │
                                           └──────────────────────────┘
```

### Container Startup Order

```
MongoDB ──────────────────────────────────┐
                                          ├──> aas-environment
Keycloak-DB (PostgreSQL) ──> Keycloak ────┤
                                          ├──> aas-registry
                                          ├──> nginx (waits for Keycloak healthy)
                                          │
                              aas-web-ui ──┘ (waits for aas-environment)
```

---

## Phase 1: Without Reverse Proxy

In the original setup, everything ran on HTTP:

```
Browser ──HTTP:3000──> AAS Web UI
Browser ──HTTP:9096──> Keycloak
Browser ──HTTP:8081──> AAS Environment
Browser ──HTTP:8083──> AAS Registry
```

**Why this failed:**
The OAuth2 Authorization Code flow with PKCE requires **`crypto.subtle`** for code challenge generation. The browser only allows `crypto.subtle` in a **secure context**, which means:
- `https://` (any port), OR
- `http://localhost` or `http://127.0.0.1`

Since `http://192.168.56.212` is neither HTTPS nor localhost, the AAS GUI threw:
```
Failed to initiate OAuth2 authorization flow
TypeError: Failed to fetch
```

---

## Phase 2: With Reverse Proxy (Current)

nginx terminates TLS and uses **path-based routing** on a single port so the
browser only talks to one origin (`:8443`) for both the SPA and the API:

```
Browser ──HTTPS:8443──> nginx ──/shells,/submodels,/concept-descriptions──> aas-environment:8081
                       │──/*──────────────────────────────> aas-web-ui:3000
Browser ──HTTPS:9443──> nginx ────────────────────────────> Keycloak (:8080)
Browser ──HTTP:8081───> AAS Environment (direct, debugging)
Browser ──HTTP:8083───> AAS Registry (Swagger)
```

**Key decisions:**
- Ports 8443/9443 used instead of 443 because Docker runs in **rootless mode** (can't bind ports < 1024)
- API paths (`/shells`, `/submodels`, `/concept-descriptions`) proxied through the same port as the SPA — avoids mixed-content and self-signed-cert-per-port issues
- nginx passes `X-Forwarded-*` headers so Keycloak generates correct external HTTPS URLs
- AAS Environment/Registry stay accessible on direct HTTP ports for debugging and server-to-server communication

> Full details: [REVERSE-PROXY.md](REVERSE-PROXY.md)

### nginx HTTPS Flow

```
Browser                    nginx                         Backend
   │                          │                              │
   │──GET /──────────────────>│                              │
   │   (TLS on :8443)         │                              │
   │                          │──proxy_pass─────────────────>│  aas-web-ui:3000
   │                          │  (X-Forwarded-Proto: https) │
   │                          │  (X-Forwarded-Host: 192..)  │
   │<─────response────────────│<─────────────────────────────│
```

---

## Authentication Flow - Step by Step

### OAuth2 Authorization Code Flow with PKCE

```
Step 1: User clicks "Login" in AAS Web UI
──────────────────────────────────────────

  AAS Web UI reads basyx-infra.yml:
    issuer: https://192.168.56.212:9443/realms/BaSyx
    clientId: basyx-web-ui


Step 2: OIDC Discovery
───────────────────────

  AAS Web UI fetches:
    https://192.168.56.212:9443/realms/BaSyx/.well-known/openid-configuration

  Keycloak returns JSON with endpoints:
    authorization_endpoint: https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/auth
    token_endpoint:         https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/token
    jwks_uri:               https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/certs


Step 3: PKCE Code Challenge Generation
──────────────────────────────────────

  AAS Web UI generates (in browser):
    code_verifier  = random 43-128 char string
    code_challenge = BASE64URL(SHA256(code_verifier))
                       ↑ This requires crypto.subtle (HTTPS or localhost only!)


Step 4: Browser Redirect to Keycloak
─────────────────────────────────────

  Browser navigates to:
    https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/auth
      ?response_type=code
      &client_id=basyx-web-ui
      &redirect_uri=https://192.168.56.212:8443/
      &code_challenge=EixUz7...
      &code_challenge_method=S256
      &scope=openid profile email roles
      &state=abc123


Step 5: User Logs In at Keycloak
─────────────────────────────────

  User sees Keycloak login form at https://192.168.56.212:9443
  Enters credentials (e.g., admin/admin)
  Keycloak validates against PostgreSQL database


Step 6: Keycloak Redirects Back with Auth Code
───────────────────────────────────────────────

  Browser redirects to:
    https://192.168.56.212:8443/?code=SplxlO...&state=abc123


Step 7: AAS Web UI Exchanges Code for Token
────────────────────────────────────────────

  AAS Web UI sends (server-side):
    POST https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/token
      grant_type=authorization_code
      code=SplxlO...
      redirect_uri=https://192.168.56.212:8443/
      client_id=basyx-web-ui
      code_verifier=abc...  (original verifier, to prove PKCE)


Step 8: Keycloak Returns JWT Token
───────────────────────────────────

  Response contains:
    access_token: eyJhbGciOiJSUzI1NiIs...
    (JWT signed by Keycloak, contains user info + roles)

  JWT payload (decoded):
    {
      "iss": "https://192.168.56.212:9443/realms/BaSyx",
      "sub": "...",
      "preferred_username": "admin",
      "realm_access": { "roles": ["admin"] },
      "exp": ...
    }


Step 9: API Calls with JWT
────────────────────────────

  AAS Web UI sends API requests with token (same origin, via nginx path routing):

    GET https://192.168.56.212:8443/shells
    Authorization: Bearer eyJhbGciOiJSUzI1NiIs...

  nginx routes /shells → aas-environment:8081


Step 10: AAS Environment Validates JWT
───────────────────────────────────────

  AAS Environment checks the token:
    1. Fetches signing keys from http://keycloak:8080/realms/BaSyx/protocol/openid-connect/certs
       (internal Docker network, no TLS needed)
    2. Verifies JWT signature
    3. Checks issuer matches https://192.168.56.212:9443/realms/BaSyx
    4. Checks token hasn't expired
    5. Checks RBAC rules for the user's roles

  If valid → returns AAS data
  If invalid → returns 401/403
```

### Authentication Diagram (Visual)

```
 ┌────────┐     ┌──────────┐     ┌──────────┐     ┌──────────────┐
 │ Browser│     │   nginx   │     │ AAS Web  │     │   Keycloak   │
 │        │     │  (TLS)    │     │   UI     │     │   (:8080)    │
 └───┬────┘     └─────┬─────┘     └────┬─────┘     └──────┬───────┘
     │                │                 │                   │
     │ 1. GET /       │                 │                   │
     │───────────────>│────────────────>│                   │
     │                │                 │                   │
     │ 2. Login page  │                 │                   │
     │<───────────────│<────────────────│                   │
     │                │                 │                   │
     │ 3. Click Login │                 │                   │
     │                │                 │ 4. Discover OIDC  │
     │                │                 │   endpoints       │
     │                │                 │──────────────────>│
     │                │                 │<──────────────────│
     │                │                 │                   │
     │ 5. Redirect to Keycloak login    │                   │
     │<───────────────│<────────────────│                   │
     │                │                 │                   │
     │ 6. GET /realms/.../auth          │                   │
     │───────────────>│─────────────────│──────────────────>│
     │                │                 │                   │
     │ 7. Login form  │                 │                   │
     │<───────────────│<────────────────│──────────────────<│
     │                │                 │                   │
     │ 8. Submit credentials            │                   │
     │───────────────>│─────────────────│──────────────────>│
     │                │                 │                   │
     │ 9. Redirect: /?code=xxx          │                   │
     │<───────────────│<────────────────│──────────────────<│
     │                │                 │                   │
     │ 10. Exchange code for token      │                   │
     │                │                 │  POST /token      │
     │                │                 │──────────────────>│
     │                │                 │<──────────────────│
     │                │                 │  { access_token } │
     │                │                 │                   │
     │ 11. Logged in! │                 │                   │
     │<───────────────│<────────────────│                   │
     │                │                 │                   │
     │ 12. GET /shells (with JWT)       │                   │
     │───────────────>│────────────────>│                   │
     │                │                 │ 13. Validate JWT  │
     │                │                 │──────────────────>│
     │                │                 │  (fetch certs)    │
     │                │                 │<──────────────────│
     │ 14. AAS data   │                 │                   │
     │<───────────────│<────────────────│                   │
```

---

## Configuration Files Reference

### 1. `.env` - Environment Variables

| Line | Variable | Value | Used By |
|------|----------|-------|---------|
| 2 | `KC_BOOTSTRAP_ADMIN_USERNAME` | `admin` | docker-compose.yml:95 |
| 3 | `KC_BOOTSTRAP_ADMIN_PASSWORD` | `admin` | docker-compose.yml:96 |
| 6 | `KC_DB_USERNAME` | `keycloak` | docker-compose.yml:99, 80, 85 |
| 7 | `KC_DB_PASSWORD` | `keycloak_db_pass` | docker-compose.yml:100, 81 |
| 14 | `MONGO_USERNAME` | `mongoAdmin` | application.properties:10 |
| 15 | `MONGO_PASSWORD` | `mongoPassword` | application.properties:11 |
| 18 | `HOST_IP` | `192.168.56.212` | Multiple files (see below) |

### 2. `docker-compose.yml` - Container Orchestration

| Lines | Section | Purpose |
|-------|---------|---------|
| 2-15 | `mongo` | MongoDB database for AAS data |
| 17-33 | `aas-environment` | AAS REST API server |
| 35-54 | `aas-ui` | AAS Web UI (Next.js) |
| 56-73 | `aas-registry` | AAS discovery registry |
| 75-88 | `keycloak-db` | PostgreSQL for Keycloak |
| 90-122 | `keycloak` | OAuth2 identity provider |
| 128-143 | `nginx` | HTTPS reverse proxy |

**Key settings:**

| File Line | Setting | Purpose |
|-----------|---------|---------|
| 24 | `HOST_IP=${HOST_IP}` | Passes IP to aas-environment for `${HOST_IP}` substitution |
| 51 | `./basyx-infra.yml:/basyx-infra.yml` | Mounts GUI config with OAuth2 settings |
| 93 | `command: start-dev --import-realm` | Starts Keycloak and imports realm JSON |
| 101 | `KC_HOSTNAME: ${HOST_IP}` | Keycloak's public hostname |
| 102 | `KC_PROXY_HEADERS: "xforwarded"` | Trust X-Forwarded-* from nginx |
| 104 | `KC_HOSTNAME_PORT: "9443"` | External port for OIDC URLs |
| 107 | `KC_HOSTNAME_STRICT_HTTPS: "true"` | Generate https:// URLs |
| 108 | `KC_HEALTH_ENABLED: "true"` | Enable /health/ready endpoint |
| 109-114 | `healthcheck` | TCP check on port 8080 |
| 116 | `realm-export.json` mount | Imports realm on first start |
| 132-134 | nginx ports `8443, 9443` | HTTPS entry points |

### 3. `basyx-infra.yml` - AAS GUI Configuration

This file is read by the **AAS Web UI** (Next.js) to know where services are and how to authenticate.

| Line | Setting | Purpose |
|------|---------|---------|
| 9 | `baseUrl: https://192.168.56.212:8443/shells` | AAS shell repository endpoint (proxied by nginx) |
| 12 | `baseUrl: https://192.168.56.212:8443/submodels` | Submodel repository endpoint (proxied by nginx) |
| 15 | `baseUrl: https://192.168.56.212:8443/concept-descriptions` | Concept description endpoint (proxied by nginx) |
| 17 | `type: oauth2` | Enable OAuth2 authentication |
| 19 | `flow: auth_code` | Use Authorization Code flow |
| 21 | `issuer: "https://192.168.56.212:9443/realms/BaSyx"` | Keycloak OIDC issuer URL |
| 22 | `clientId: "basyx-web-ui"` | OAuth2 client identifier |

### 4. `nginx/nginx.conf` - Reverse Proxy

| Line | Setting | Purpose |
|------|---------|---------|
| 13 | `listen 80` | HTTP redirect to HTTPS |
| 20 | `listen 8443 ssl` | Accept HTTPS on port 8443 for UI + API |
| 21 | `server_name 192.168.56.212` | Match requests for this hostname |
| 23-24 | `ssl_certificate/key` | Self-signed TLS cert paths |
| 27-34 | `location ~ ^/(shells\|submodels\|concept-descriptions)` | Path-based routing: API → aas-environment:8081 |
| 37 | `proxy_pass http://aas-web-ui:3000` | Catch-all: SPA static files |
| 41-48 | `X-Forwarded-*` headers | Tell backends the original protocol/host/port |
| 51 | `listen 9443 ssl` | Accept HTTPS on port 9443 for Keycloak |
| 58 | `proxy_pass http://keycloak:8080` | Forward to Keycloak container |
| 62-64 | `X-Forwarded-*` headers | So Keycloak generates correct external URLs |

### 5. `basyx/application.properties` - AAS Environment Config

This is the Spring Boot configuration for the AAS Environment server.

| Line | Setting | Purpose |
|------|---------|---------|
| 1 | `server.port=8081` | Listen port |
| 19 | `basyx.externalurl=http://${HOST_IP}:8081` | Public URL for AAS Environment |
| 22 | `authorization.enabled=true` | Enable RBAC authorization |
| 24 | `jwtBearerTokenProvider=keycloak` | Validate JWTs via Keycloak |
| 30 | `issuer-uri=https://${HOST_IP}:9443/realms/BaSyx` | JWT issuer to validate against |
| 32 | `jwk-set-uri=http://keycloak:8080/.../certs` | Internal URL to fetch signing keys |
| 36 | `allowed-origins=https://${HOST_IP}:8443` | CORS: allow browser requests from GUI |
| 38 | `allowed-headers=*` | CORS: allow all headers |

### 6. `basyx/aas-registry.yml` - AAS Registry Config

| Line | Setting | Purpose |
|------|---------|---------|
| 9 | `issuer-uri: https://${HOST_IP}:9443/realms/BaSyx` | JWT issuer to validate against |
| 11 | `jwk-set-uri: http://keycloak:8080/.../certs` | Internal URL to fetch signing keys |
| 23 | `authorization.enabled: false` | Auth disabled for Swagger UI access |
| 30 | `allowed-origins: 'https://${HOST_IP}:8443'` | CORS: allow browser requests from GUI |

### 7. `keycloak/realm-export.json` - Keycloak Realm

| Lines | Setting | Purpose |
|-------|---------|---------|
| 2 | `"realm": "BaSyx"` | Realm name (matches issuer URL) |
| 25 | `"clientId": "basyx-web-ui"` | Public OAuth2 client for the GUI |
| 27 | `"publicClient": true` | No client secret needed (browser-based) |
| 29 | `"standardFlowEnabled: true` | Enable Authorization Code flow |
| 32-34 | `"redirectUris": ["https://192.168.56.212:8443/*"]` | Allowed callback URLs after login |
| 35-37 | `"webOrigins": ["https://192.168.56.212:8443"]` | CORS origins for the GUI |
| 45 | `"post.logout.redirect.uris": "https://..."` | Allowed logout redirect URLs |
| 49-62 | `basyx-admin` client | Confidential client for service accounts |
| 66-82 | Realm roles | `admin`, `reader`, `uploader` |
| 84-138 | Users | admin/admin, reader/reader, uploader/uploader |
| 174-307 | Client scopes | openid, profile, email, roles (with mappers) |

### 8. `basyx/rbac_rules.json` - AAS Environment RBAC

Defines what each role can do:

| Role | Permissions |
|------|------------|
| `admin` | CREATE, READ, UPDATE, DELETE, EXECUTE on everything |
| `reader` | READ only on everything |
| `uploader` | CREATE, READ, UPDATE (no DELETE) |

### 9. TLS Certificates

| File | Purpose |
|------|---------|
| `nginx/certs/server.crt` | Self-signed X.509 certificate (CN=192.168.56.212) |
| `nginx/certs/server.key` | TLS private key |

Generated with:
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/server.key \
  -out nginx/certs/server.crt \
  -subj "/CN=192.168.56.212"
```

---

## Configuration Workflow

This section describes the order in which settings flow through the system.

### Workflow 1: OAuth2 Authentication Configuration

```
Step 1: Define variables
  .env:18           HOST_IP=192.168.56.212

Step 2: Keycloak hostname config
  docker-compose.yml:101   KC_HOSTNAME=${HOST_IP}
  docker-compose.yml:104   KC_HOSTNAME_PORT="9443"
  docker-compose.yml:107   KC_HOSTNAME_STRICT_HTTPS="true"
  docker-compose.yml:102   KC_PROXY_HEADERS="xforwarded"
  ↓
  Keycloak generates OIDC URLs as:
    https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/auth

Step 3: Realm import
  docker-compose.yml:116   mounts keycloak/realm-export.json
  keycloak/realm-export.json:25   clientId: "basyx-web-ui"
  keycloak/realm-export.json:32   redirectUris: ["https://192.168.56.212:8443/*"]
  ↓
  Keycloak registers the client with matching redirect URIs

Step 4: GUI reads issuer
  docker-compose.yml:51    mounts basyx-infra.yml
  basyx-infra.yml:21       issuer: "https://192.168.56.212:9443/realms/BaSyx"
  basyx-infra.yml:22       clientId: "basyx-web-ui"
  ↓
  GUI discovers endpoints via OIDC discovery

Step 5: nginx terminates TLS
  nginx/nginx.conf:35      listen 9443 ssl
  nginx/nginx.conf:42      proxy_pass http://keycloak:8080
  nginx/nginx.conf:46-48   X-Forwarded-* headers
  ↓
  Browser reaches Keycloak over HTTPS, Keycloak sees correct external URL

Step 6: Backend validates JWT
  application.properties:30   issuer-uri=https://${HOST_IP}:9443/realms/BaSyx
  application.properties:32   jwk-set-uri=http://keycloak:8080/.../certs
  ↓
  AAS Environment verifies JWT signature and issuer
```

### Workflow 2: CORS Configuration

```
Step 1: GUI origin
  nginx/nginx.conf:20       listen 8443 ssl
  ↓
  Browser accesses GUI at https://192.168.56.212:8443

  NOTE: With path-based routing, API calls are same-origin (also :8443),
  so CORS headers are not strictly required. They remain as a safety net
  for direct :8081 access or future cross-origin clients.

Step 2: AAS Environment allows this origin
  application.properties:36  cors.allowed-origins=https://${HOST_IP}:8443
  ↓
  AAS Environment accepts API requests from https://192.168.56.212:8443

Step 3: Keycloak allows this origin
  keycloak/realm-export.json:35  webOrigins: ["https://192.168.56.212:8443"]
  ↓
  Keycloak allows CORS from the GUI

Step 4: Registry allows this origin
  aas-registry.yml:30        allowed-origins: 'https://${HOST_IP}:8443'
  ↓
  AAS Registry accepts requests from the GUI
```

### Workflow 3: JWT Validation Chain

```
1. Browser sends request with Authorization: Bearer <JWT>
   ↓
2. AAS Environment receives request (port 8081)
   ↓
3. Spring Security intercepts (application.properties:22, authorization.enabled=true)
   ↓
4. Checks JWT issuer (application.properties:30, issuer-uri)
   Token's "iss" claim must equal https://192.168.56.212:9443/realms/BaSyx
   ↓
5. Fetches signing keys from Keycloak (application.properties:32, jwk-set-uri)
   http://keycloak:8080/realms/BaSyx/protocol/openid-connect/certs
   (internal Docker network, no TLS needed)
   ↓
6. Verifies JWT signature using fetched keys
   ↓
7. Checks RBAC rules (rbac_rules.json)
   User's roles (from JWT realm_access.roles) must match required role
   ↓
8. Returns 200 + data, or 401/403
```

---

## Users & Roles

Pre-configured users in `keycloak/realm-export.json`:

| Username | Password | Role | Permissions |
|----------|----------|------|-------------|
| `admin` | `admin` | `admin` | Full CRUD + Execute on all AAS resources |
| `reader` | `reader` | `reader` | Read-only access |
| `uploader` | `uploader` | `uploader` | Create, Read, Update (no Delete) |

Keycloak admin console: `https://192.168.56.212:9443/admin` (login: admin/admin)

---

## RBAC Rules

### AAS Environment (`basyx/rbac_rules.json`)

| Role | CREATE | READ | UPDATE | DELETE | EXECUTE |
|------|--------|------|--------|--------|---------|
| admin | yes | yes | yes | yes | yes |
| reader | - | yes | - | - | - |
| uploader | yes | yes | yes | - | - |

### AAS Registry (`basyx/rbac_rules_registry.json`)

| Role | CREATE | READ | UPDATE | DELETE |
|------|--------|------|--------|--------|
| admin | yes | yes | yes | yes |
| reader | - | yes | - | - |

> Note: Registry auth is currently **disabled** (`aas-registry.yml:23`) for Swagger UI access.

---

## Troubleshooting

### "Failed to initiate OAuth2 authorization flow"

**Cause:** Browser not in secure context. PKCE requires `crypto.subtle`.
**Fix:** Access via `https://192.168.56.212:8443` (nginx with TLS). Accept the self-signed cert warning. See [REVERSE-PROXY.md](REVERSE-PROXY.md).

### "TypeError: Failed to load" from other PCs

**Cause:** Browser hasn't accepted the self-signed cert for `:8443` (or `:9443`). Navigation shows the cert warning; background `fetch()` does not.
**Fix:** Open `https://192.168.56.212:8443` and accept the warning, then do the same for `:9443`.

### Keycloak 502 Bad Gateway

**Cause:** nginx started before Keycloak was ready.
**Fix:** Healthcheck in docker-compose.yml:109-114 ensures nginx waits for Keycloak.

### Port 80 redirect doesn't work in browser

**Cause:** Browser cache or HSTS from a previous session.
**Fix:** Clear Safari cache/cookies, or test in Chrome incognito.

### Login redirects to wrong URL (http://192.168.56.212/admin/)

**Cause:** Keycloak not aware of reverse proxy. Generates wrong OIDC URLs.
**Fix:** `KC_PROXY_HEADERS: "xforwarded"` (docker-compose.yml:102) + X-Forwarded-* headers (nginx.conf:25-26, 47-48).

### Swagger UI returns 401/403

**Cause:** Registry authorization blocks unauthenticated Swagger requests.
**Fix:** Set `authorization.enabled: false` (aas-registry.yml:23).

### CORS errors in browser console

**Cause:** `allowed-origins` doesn't match the browser's origin.
**Fix:** Ensure `application.properties:36` and `realm-export.json:35` match the GUI URL (`https://192.168.56.212:8443`).

### "Keycloak" container stuck in "Waiting"

**Cause:** Healthcheck failing (usually `curl` not found in container).
**Fix:** Use TCP healthcheck: `bash -c 'echo > /dev/tcp/localhost/8080'` (docker-compose.yml:110).

### OIDC Discovery returns wrong authorization_endpoint

**Verify:** Open `https://192.168.56.212:9443/realms/BaSyx/.well-known/openid-configuration` in browser.
Correct output should show `authorization_endpoint` starting with `https://192.168.56.212:9443/...`.

### Restart command

```bash
/opt/podman/bin/podman compose down && /opt/podman/bin/podman compose up -d
```

Note: Use `podman compose` with the external `docker-compose` provider (Docker Desktop has a bad CPU type on this machine).

---

## File Tree

```
basyx-setup/
├── .env                                    # Environment variables (HOST_IP, DB creds)
├── docker-compose.yml                      # Container definitions & orchestration
├── basyx-infra.yml                         # AAS GUI config (OAuth2 issuer, API URLs)
├── ARCHITECTURE.md                         # This file
├── REVERSE-PROXY.md                        # HTTPS & path-based routing details
│
├── basyx/
│   ├── application.properties              # AAS Environment config (JWT, CORS, DB)
│   ├── aas-registry.yml                    # AAS Registry config (JWT, CORS, DB)
│   ├── rbac_rules.json                     # RBAC rules for AAS Environment
│   ├── rbac_rules_registry.json            # RBAC rules for AAS Registry
│   └── static/
│       └── swagger-initializer.js          # Swagger UI config
│
├── keycloak/
│   └── realm-export.json                   # Keycloak realm (clients, users, roles)
│
├── nginx/
│   ├── nginx.conf                          # Reverse proxy config (TLS, proxy_pass)
│   └── certs/
│       ├── server.crt                      # Self-signed TLS certificate
│       └── server.key                      # TLS private key
│
└── aas/                                    # AAS submodel/shell JSON files (mounted)
```
