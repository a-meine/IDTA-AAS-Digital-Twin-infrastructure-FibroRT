# BaSyx AAS Server Authorization - Implementation Plan

## Table of Contents

1. [Overview](#overview)
2. [Current State](#current-state)
3. [Architecture](#architecture)
4. [Prerequisites](#prerequisites)
5. [Implementation Steps](#implementation-steps)
   - [Step 1: Create Environment Variables](#step-1-create-environment-variables)
   - [Step 2: Add Keycloak and PostgreSQL Services](#step-2-add-keycloak-and-postgresql-services)
   - [Step 3: Create RBAC Rules](#step-3-create-rbac-rules)
   - [Step 4: Enable Authorization on AAS Environment](#step-4-enable-authorization-on-aas-environment)
   - [Step 5: Enable Authorization on AAS Registry](#step-5-enable-authorization-on-aas-registry)
   - [Step 6: Configure Web UI for OAuth2 Login](#step-6-configure-web-ui-for-oauth2-login)
   - [Step 7: Post-Start Keycloak Realm Setup](#step-7-post-start-keycloak-realm-setup)
   - [Step 8: Verify Authorization](#step-8-verify-authorization)
6. [File Change Summary](#file-change-summary)
7. [Glossary](#glossary)

---

## Overview

This plan secures all BaSyx AAS components with **OAuth2/OIDC + RBAC** authorization using **Keycloak** as the identity provider. After implementation, all API calls will require a valid JWT token, and access will be controlled by role-based rules (admin, reader, uploader).

**For beginners:** Think of this like adding a lock to your front door. Right now, anyone can access your AAS server. After this plan, users must log in (authentication) and prove they have the right role (authorization) before accessing any data.

**Estimated time:** 1-2 hours for a beginner, 20-30 minutes for experienced developers.

---

## Current State

Your stack currently has **zero authentication or authorization**:

- `basyx-infra.yml` declares `security.type: none`
- `application.properties` has no Spring Security config
- CORS is wide open (`*`)
- All API endpoints are publicly accessible

**Current stack:** BaSyx Java v2.0.0-milestone-13, MongoDB 7, AAS Web UI, 4 Docker containers.

**What we're adding:** Keycloak (identity provider) + PostgreSQL (Keycloak database) + RBAC rules (access control).

---

## Architecture

### Before (Current)
```
┌──────────┐     ┌──────────────────┐
│  Browser  │────▶│ AAS Environment  │────▶ MongoDB
│           │     │ (no auth)        │
│           │     ├──────────────────┤
│           │────▶│ AAS Registry     │
└──────────┘     └──────────────────┘
```

### After (With Authorization)
```
                          ┌─────────────────────────────┐
                          │        Keycloak :9096        │
                          │   (Identity Provider)        │
                          └──────────┬──────────────────┘
                                     │
                          ┌──────────▼──────────────────┐
                          │     PostgreSQL :5432         │
                          │     (KC database only)       │
                          │     DB: keycloak             │
                          └─────────────────────────────┘

                          ┌─────────────────────────────┐
                          │   AAS Environment :8081      │
  Browser ───────────────▶│   + RBAC (rbac_rules.json)   │────▶ MongoDB :27017
  (Web UI :3000)          │   + Spring Security JWT      │
                          ├──────────────────────────────┤
                          │   AAS Registry :8083          │
                          │   + RBAC (rbac_rules_reg.json)│
                          └──────────────────────────────┘
```

### Flow (How It Works)
1. **User opens Web UI** -> redirected to Keycloak login page
2. **User logs in** -> Keycloak authenticates and issues a JWT token
3. **Web UI sends API request** -> includes JWT in `Authorization: Bearer <token>` header
4. **AAS Environment receives request** -> validates JWT against Keycloak
5. **RBAC check** -> compares user's role against `rbac_rules.json`
6. **Access granted or denied** -> returns data or 403 Forbidden

### Why PostgreSQL for Keycloak?

Keycloak **does not support MongoDB** (it was removed years ago). Keycloak supports:
- PostgreSQL (recommended for production)
- MySQL / MariaDB
- H2 (embedded, dev only, data lost on restart)

We use PostgreSQL because it is the most common choice, works well with Keycloak, and your BaSyx data stays in MongoDB (two separate databases, each serving its purpose).

---

## Prerequisites

- Docker and Docker Compose installed
- Basic understanding of your current BaSyx setup (see `README.md`)
- Terminal/command line access

---

## Implementation Steps

### Step 1: Create Environment Variables

**Purpose:** Centralize secrets (passwords, client secrets) so they are not hardcoded in config files.

**File to create:** `.env`

```env
# Keycloak Admin (login credentials for KC admin console)
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=admin

# Keycloak PostgreSQL database
KC_DB_USERNAME=keycloak
KC_DB_PASSWORD=keycloak_db_pass

# Keycloak Client Secrets (fill AFTER creating clients in KC admin console)
BASYX_WEB_UI_CLIENT_SECRET=
BASYX_ADMIN_CLIENT_SECRET=

# MongoDB (centralize existing credentials)
MONGO_USERNAME=mongoAdmin
MONGO_PASSWORD=mongoPassword
```

**File to edit:** `.gitignore` -- add `.env` at the end

```gitignore
venv
.env
```

**Explanation:**
- `.env` is a standard file for environment variables in Docker Compose
- `.gitignore` prevents secrets from being committed to version control
- After creating Keycloak clients (Step 7), you will paste the client secrets here

---

### Step 2: Add Keycloak and PostgreSQL Services

**Purpose:** Add two new Docker containers to your stack.

**File to edit:** `docker-compose.yml`

#### 2.1 Add PostgreSQL service (for Keycloak)

Add this service at the end of the `services:` section:

```yaml
  keycloak-db:
    container_name: keycloak-db
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: keycloak
      POSTGRES_USER: ${KC_DB_USERNAME}
      POSTGRES_PASSWORD: ${KC_DB_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${KC_DB_USERNAME}"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**What this does:** Creates a PostgreSQL database specifically for Keycloak. The healthcheck ensures Keycloak does not start until the database is ready.

#### 2.2 Add Keycloak service

Add this service after `keycloak-db`:

```yaml
  keycloak:
    container_name: keycloak
    image: quay.io/keycloak/keycloak:latest
    command: start-dev
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: ${KC_BOOTSTRAP_ADMIN_USERNAME}
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KC_BOOTSTRAP_ADMIN_PASSWORD}
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://keycloak-db:5432/keycloak
      KC_DB_USERNAME: ${KC_DB_USERNAME}
      KC_DB_PASSWORD: ${KC_DB_PASSWORD}
    ports:
      - "9096:8080"
    depends_on:
      keycloak-db:
        condition: service_healthy
```

**What this does:** Starts Keycloak (the identity provider) on port 9096. The `start-dev` command runs in development mode (no HTTPS, simplified setup).

#### 2.3 Update existing services

Update `aas-environment` to:
- Depend on Keycloak being ready
- Mount the RBAC rules file

```yaml
  aas-environment:
    image: eclipsebasyx/aas-environment:2.0.0-milestone-13
    container_name: aas-environment
    ports:
      - "8081:8081"
    depends_on:
      mongo:
        condition: service_started
      keycloak:
        condition: service_started
    volumes:
      - ./basyx/application.properties:/app/config/application.properties
      - ./basyx/rbac_rules.json:/app/classes/rbac_rules.json
```

Update `aas-registry` similarly:

```yaml
  aas-registry:
    image: eclipsebasyx/aas-registry-log-mongodb:2.0.0-milestone-13
    container_name: aas-registry
    ports:
      - "8083:8080"
    depends_on:
      mongo:
        condition: service_started
      keycloak:
        condition: service_started
    volumes:
      - ./basyx/aas-registry.yml:/app/config/application.yml
      - ./basyx/rbac_rules_registry.json:/app/classes/rbac_rules.json
```

---

### Step 3: Create RBAC Rules

**Purpose:** Define who can do what with your AAS resources.

**File to create:** `basyx/rbac_rules.json`

```json
[
  {
    "role": "admin",
    "action": ["CREATE", "READ", "UPDATE", "DELETE"],
    "targetInformation": {
      "@type": "aas-environment",
      "aasIds": "*",
      "submodelIds": "*",
      "conceptDescriptionIds": "*"
    }
  },
  {
    "role": "reader",
    "action": "READ",
    "targetInformation": {
      "@type": "aas-environment",
      "aasIds": "*",
      "submodelIds": "*",
      "conceptDescriptionIds": "*"
    }
  },
  {
    "role": "uploader",
    "action": ["CREATE", "READ"],
    "targetInformation": {
      "@type": "aas-environment",
      "aasIds": "*",
      "submodelIds": "*",
      "conceptDescriptionIds": "*"
    }
  }
]
```

**Explanation of RBAC rules:**
- **Role:** The role assigned to a user in Keycloak (e.g., `admin`, `reader`, `uploader`)
- **Action:** What operations are allowed (`CREATE`, `READ`, `UPDATE`, `DELETE`)
- **targetInformation:** Which resources the rule applies to
  - `"*"` means "all resources"
  - `"@type": "aas-environment"` means this rule applies to the AAS Environment component
  - You can restrict to specific AAS IDs or submodel IDs if needed

**File to create:** `basyx/rbac_rules_registry.json`

Same structure, but for the AAS Registry component:

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
  }
]
```

**Role meanings:**

| Role | Permissions | Who |
|------|------------|-----|
| `admin` | Full CRUD (Create, Read, Update, Delete) | System administrators |
| `reader` | Read only | End users, auditors, customers |
| `uploader` | Create + Read (no update/delete) | Manufacturers uploading DPPs |

---

### Step 4: Enable Authorization on AAS Environment

**Purpose:** Tell the AAS Environment to validate JWT tokens and check RBAC rules.

**File to edit:** `basyx/application.properties`

Append these lines at the end of the file:

```properties
# === Authorization ===
basyx.feature.authorization.enabled = true
basyx.feature.authorization.type = rbac
basyx.feature.authorization.jwtBearerTokenProvider = keycloak
basyx.feature.authorization.rbac.file = classpath:rbac_rules.json

# Keycloak JWT validation
spring.security.oauth2.resourceserver.jwt.issuer-uri = http://keycloak:8080/realms/BaSyx

# AAS Environment preconfiguration (for authenticated package uploads)
basyx.aasenvironment.authorization.preconfiguration.token-endpoint = http://keycloak:8080/realms/BaSyx/protocol/openid-connect/token
basyx.aasenvironment.authorization.preconfiguration.grant-type = CLIENT_CREDENTIALS
basyx.aasenvironment.authorization.preconfiguration.client-id = basyx-admin
basyx.aasenvironment.authorization.preconfiguration.client-secret = ${BASYX_ADMIN_CLIENT_SECRET}

# Tighten CORS (restrict to your Web UI origin)
basyx.cors.allowed-origins=http://localhost:3000
basyx.cors.allowed-methods=GET,POST,PUT,PATCH,DELETE,OPTIONS,HEAD
basyx.cors.allowed-headers=*
basyx.cors.allow-credentials=true
```

**Explanation of each property:**
- `basyx.feature.authorization.enabled = true` -- turns on authorization
- `basyx.feature.authorization.type = rbac` -- uses Role-Based Access Control
- `basyx.feature.authorization.jwtBearerTokenProvider = keycloak` -- validates tokens against Keycloak
- `basyx.feature.authorization.rbac.file = classpath:rbac_rules.json` -- loads rules from this file
- `spring.security.oauth2.resourceserver.jwt.issuer-uri` -- where to validate JWT tokens (Keycloak realm URL)
- `basyx.aasenvironment.authorization.preconfiguration.*` -- credentials for backend service-to-service calls
- `basyx.cors.allowed-origins` -- only allow requests from your Web UI (security best practice)

**Note:** The `issuer-uri` uses `keycloak:8080` (Docker internal network) while external access is on port `9096`.

---

### Step 5: Enable Authorization on AAS Registry

**Purpose:** Apply the same authorization to the AAS Registry component.

**File to edit:** `basyx/aas-registry.yml`

Replace the entire content with:

```yaml
spring:
  mongodb:
    uri: mongodb://mongoAdmin:mongoPassword@mongo:27017/admin
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: http://keycloak:8080/realms/BaSyx
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
        file: classpath:rbac_rules.json
  cors:
    allowed-origins: 'http://localhost:3000'
    allowed-methods: GET,POST,PATCH,DELETE,PUT,OPTIONS,HEAD
```

**What changed:** Added `basyx.feature.*` for authorization and `spring.security.oauth2.resourceserver.jwt` for JWT validation.

---

### Step 6: Configure Web UI for OAuth2 Login

**Purpose:** Make the Web UI redirect users to Keycloak for login.

**File to edit:** `basyx-infra.yml`

Replace the entire content with:

```yaml
infrastructures:
  default: secured
  secured:
    name: Secured BaSyx Environment
    template: mono-repo
    components:
      aasRepository:
        baseUrl: http://localhost:8081/shells
      submodelRepository:
        baseUrl: http://localhost:8081/submodels
      conceptDescriptionRepository:
        baseUrl: http://localhost:8081/concept-descriptions
    security:
      type: oauth2
      config:
        flow: auth_code
        issuer: "http://localhost:9096/realms/BaSyx"
        clientId: "basyx-web-ui"
```

**Explanation:**
- `security.type: oauth2` -- enables OAuth2 login in the Web UI
- `flow: auth_code` -- uses Authorization Code flow (recommended for browser-based apps)
- `issuer` -- Keycloak public URL (where the browser can reach Keycloak)
- `clientId` -- the client ID you will create in Keycloak (Step 7)

**Note:** The `issuer` uses `localhost:9096` (browser-accessible) while AAS components use `keycloak:8080` (Docker internal network).

---

### Step 7: Post-Start Keycloak Realm Setup

**Purpose:** Configure Keycloak with your BaSyx realm, clients, roles, and users.

**After starting the stack with `docker compose up`:**

1. **Access Keycloak Admin Console**
   - Open browser: `http://localhost:9096`
   - Login: `admin` / `admin` (or whatever you set in `.env`)

2. **Create a Realm**
   - Click "Create Realm" button
   - Name: `BaSyx`
   - Click "Create"

3. **Create Clients**
   - Go to **Clients** -> **Create client**
   - **Client 1:** `basyx-web-ui`
     - Client type: `OpenID Connect`
     - Valid redirect URIs: `http://localhost:3000/*`
     - Web origins: `http://localhost:3000`
     - Save -> go to **Credentials** tab -> copy the **Client Secret**
   - **Client 2:** `basyx-admin`
     - Client type: `OpenID Connect`
     - Authentication flow: **Service accounts roles** enabled
     - Save -> go to **Credentials** tab -> copy the **Client Secret**

4. **Create Roles**
   - Go to **Roles** -> **Create role**
   - Create: `admin`, `reader`, `uploader`

5. **Create Users**
   - Go to **Users** -> **Add user**
   - Create users (e.g., `john.doe`) and assign roles
   - Set passwords for each user

6. **Update `.env` with Client Secrets**
   - Paste the copied secrets into `.env`:
     ```env
     BASYX_WEB_UI_CLIENT_SECRET=<paste-here>
     BASYX_ADMIN_CLIENT_SECRET=<paste-here>
     ```

7. **Restart the stack**
   - Run `docker compose down && docker compose up -d`

---

### Step 8: Verify Authorization

**Purpose:** Confirm that authorization is working correctly.

**Test 1: Web UI Login**
- Visit `http://localhost:3000`
- Should redirect to Keycloak login page
- Log in with a user you created
- Should see the AAS Web UI

**Test 2: API Without Token (Should Fail)**
```bash
curl http://localhost:8081/shells
# Expected: 401 Unauthorized
```

**Test 3: API With Valid Token (Should Succeed)**
```bash
# Get a token from Keycloak
TOKEN=$(curl -s -X POST http://localhost:9096/realms/BaSyx/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=basyx-admin" \
  -d "client_secret=<your-secret>" | jq -r '.access_token')

# Use the token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8081/shells
# Expected: 200 OK with AAS list
```

**Test 4: Reader Role (Should Deny Write)**
```bash
# Login as a user with 'reader' role
# Try to delete an AAS
curl -X DELETE -H "Authorization: Bearer $READER_TOKEN" http://localhost:8081/shells/<aas-id>
# Expected: 403 Forbidden
```

---

## File Change Summary

| # | File | Action | ~Lines Changed | Purpose |
|---|------|--------|----------------|---------|
| 1 | `.env` | **Create** | 12 | Environment variables (secrets) |
| 2 | `.gitignore` | **Edit** | +1 | Prevent `.env` from being committed |
| 3 | `docker-compose.yml` | **Edit** | +35 | Add Keycloak + PostgreSQL services |
| 4 | `basyx/rbac_rules.json` | **Create** | 30 | RBAC rules for AAS Environment |
| 5 | `basyx/rbac_rules_registry.json` | **Create** | 30 | RBAC rules for AAS Registry |
| 6 | `basyx/application.properties` | **Edit** | +12 | Enable authorization on AAS Environment |
| 7 | `basyx/aas-registry.yml` | **Edit** | +12 | Enable authorization on AAS Registry |
| 8 | `basyx-infra.yml` | **Edit** | ~8 | Configure Web UI for OAuth2 |

**Total:** 3 new files, 5 edited files, ~140 lines of changes.

**Docker containers after implementation:** 6 (was 4)
- MongoDB
- AAS Environment
- AAS Registry
- AAS Web UI
- Keycloak (new)
- PostgreSQL (new)

---

## Glossary

| Term | Meaning |
|------|---------|
| **OAuth2** | Open standard for authorization. Allows third-party apps to access resources on behalf of a user. |
| **OIDC** | OpenID Connect. Layer on top of OAuth2 that adds user identity (who is logged in?). |
| **JWT** | JSON Web Token. A digitally signed token containing user info and roles. Used to prove identity. |
| **RBAC** | Role-Based Access Control. Permissions are assigned to roles, and roles are assigned to users. |
| **Keycloak** | Open-source identity and access management solution. Handles login, logout, and token issuance. |
| **Realm** | A tenant in Keycloak. Contains users, roles, and clients for your application. |
| **Client** | An application that uses Keycloak for authentication (e.g., your Web UI). |
| **Issuer URI** | The URL where Keycloak publishes its public signing keys (used to validate JWT tokens). |
| **CORS** | Cross-Origin Resource Sharing. Controls which domains can make API requests to your server. |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Keycloak won't start | Check `docker compose logs keycloak` -- usually a database connection issue |
| AAS Environment returns 401 | Ensure JWT is valid and Keycloak realm is named `BaSyx` |
| AAS Environment returns 403 | User's role does not match RBAC rules in `rbac_rules.json` |
| Web UI shows blank page | Check `basyx-infra.yml` -- ensure `security.type: oauth2` and `clientId` matches Keycloak |
| CORS errors in browser | Update `basyx.cors.allowed-origins` to include your Web UI URL |
| MongoDB connection refused | Ensure `mongo` container is running and credentials in `.env` match |

---

## Next Steps (After Implementation)

1. **Enable HTTPS** -- Use nginx reverse proxy with TLS certificates
2. **Restrict RBAC rules** -- Limit to specific AAS IDs instead of `"*"` (wildcard)
3. **Add monitoring** -- Log authentication failures and access attempts
4. **Backup Keycloak** -- PostgreSQL data includes all users, roles, and realm config
5. **Production deployment** -- Use `start` instead of `start-dev` for Keycloak, enable HTTPS

---

## References

- [BaSyx V2 Authorization Wiki](https://wiki.basyx.org/en/latest/content/user_documentation/basyx_components/v2/aas_environment/features/authorization.html)
- [BaSyx RBAC Use Case Guide](https://wiki.basyx.org/en/latest/content/concepts/use_cases/rbac.html)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [BaSyx GitHub Examples](https://github.com/eclipse-basyx/basyx-java-server-sdk/tree/main/examples/BaSyxSecured)
