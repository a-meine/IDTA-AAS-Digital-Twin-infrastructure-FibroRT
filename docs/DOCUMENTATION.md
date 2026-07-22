# BaSyx AAS Server with OAuth2 Authorization - Complete Guide

## Table of Contents
1. [What Is This Project?](#what-is-this-project)
2. [Architecture Overview](#architecture-overview)
3. [Component Deep Dive](#component-deep-dive)
4. [File-by-File Walkthrough](#file-by-file-walkthrough)
5. [How Authentication and Authorization Work](#how-authentication-and-authorization-work)
6. [Issues We Solved and How](#issues-we-solved-and-how)
7. [Known Issues and Solutions](#known-issues-and-solutions)
8. [Next Steps for Production](#next-steps-for-production)

---

## What Is This Project?

This project sets up a secure **Eclipse BaSyx** server infrastructure for managing
**Asset Administration Shells (AAS)**. An AAS is a standardized
 digital representation
of a physical asset (like a machine, vehicle, or product) used in Industry 4.0.

Think of it like this:
- A **product** (e.g., a car part) has a **digital twin** (its AAS) stored on this server
- The AAS contains **submodels** (collections of properties, like technical data,
  maintenance info, carbon footprint data)
- This server lets you **upload, view, and manage** these digital twins
- **Authorization** ensures only people with the right role can perform certain actions

We use **Keycloak** for login/authentication and **RBAC (Role-Based Access Control)**
to decide what each user can do.

---

## Architecture Overview

```
                              +------------------+
                              |    Browser/User   |
                              +--------+---------+
                                       |
                                       v
                          +------------+----------+
                          |   AAS Web UI (:3000)  |
                          |  (eclipsebasyx/aas-gui)|
                          +------------+----------+
                                       |
                          +------------+----------+
                          |                       |
                          v                       v
              +-----------+--------+   +---------+----------+
              | AAS Environment     |   |  AAS Registry     |
              | (:8081)             |   |  (:8083)          |
              | (Upload, CRUD,      |   |  (Lookup,         |
              |  Serialization)     |   |   Discovery)       |
              +-----------+--------+   +---------+----------+
                   |         |                 |
                   v         v                 v
            +------+---+ +--+----------+ +----+-----+
            | MongoDB   | |  Keycloak   | | MongoDB  |
            | (AAS data)| |  (:9096)    | | (Registry|
            |           | |  (Auth)     | |  data)   |
            +-----------+ +-----+-------+ +----------+
                              |
                              v
                       +------+-------+
                       |  PostgreSQL   |
                       |  (Keycloak DB)|
                       +--------------+
```

### The Flow

1. **User** opens the Web UI at `http://localhost:3000`
2. Web UI redirects to **Keycloak** for login
3. After login, Keycloak gives the browser a **JWT token** with the user's roles
4. The Web UI uses this token to call the **AAS Environment** API
5. The AAS Environment checks the token's roles against the **RBAC rules**
6. If authorized, the action proceeds (upload, read, delete, etc.)

---

## Component Deep Dive

### 1. AAS Environment (Port 8081)

**What it is:** The main server that stores and manages AAS data.

**Image:** `eclipsebasyx/aas-environment:2.0.0-milestone-13`

**What it does:**
- Accepts uploads of AASX, JSON, or XML files containing AAS data
- Provides REST API endpoints for CRUD operations on AAS, Submodels, and Concept Descriptions
- Handles serialization (exporting AAS data)
- Enforces RBAC authorization on every request

**Key endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/shells` | GET | List all AAS |
| `/shells` | POST | Create a new AAS |
| `/upload` | POST | Upload an AASX/JSON/XML file |
| `/submodels` | GET | List all submodels |
| `/concept-descriptions` | GET | List all concept descriptions |
| `/serialization` | GET | Export AAS data |
| `/v3/api-docs` | GET | OpenAPI documentation |
| `/swagger-ui.html` | GET | Interactive API docs |

**Configuration:** `basyx/application.properties`
- Backend: MongoDB (persistent storage)
- Authorization: RBAC enabled, Keycloak JWT provider
- RBAC rules file: `/config/rbac_rules.json` (mounted from host)
- CORS: Only allows requests from `http://localhost:3000` (the Web UI)

### 2. AAS Registry (Port 8083)

**What it is:** A lookup service that tracks where AAS data lives across multiple servers.

**Image:** `eclipsebasyx/aas-registry-log-mongodb:2.0.0-milestone-13`

**What it does:**
- Maintains a directory of AAS descriptors (metadata about AAS)
- Lets other systems discover which server holds a particular AAS
- Has its own RBAC rules (separate from the AAS Environment)

**Configuration:** `basyx/aas-registry.yml`
- Also uses MongoDB for storage
- Has its own RBAC rules file
- Has its own JWT/Keycloak configuration

### 3. AAS Web UI (Port 3000)

**What it is:** A browser-based interface for managing AAS.

**Image:** `eclipsebasyx/aas-gui:latest`

**What it does:**
- Shows a list of all AAS on the server
- Lets you upload AASX files through the browser
- Lets you view and edit AAS, submodels, and properties
- Handles Keycloak login/logout

**Configuration:** `basyx-infra.yml` (mounted into the container)
- Tells the UI where the AAS Environment API is (`http://localhost:8081`)
- Configures OAuth2 login flow with Keycloak
- Uses `auth_code` flow (browser redirects to Keycloak for login)

### 4. Keycloak (Port 9096)

**What it is:** An identity and access management system. Handles user login, passwords, and tokens.

**Image:** `quay.io/keycloak/keycloak:latest`

**What it does:**
- Provides a login page for users
- Issues JWT tokens after successful login
- Manages users, roles, and client applications
- Supports two types of clients:
  - **Public clients** (like the Web UI): The browser handles the login flow
  - **Confidential clients** (like `basyx-admin`): Use a secret for API access

**Configuration:** `keycloak/realm-export.json`

**Realm name:** `BaSyx`

**Users (pre-configured):**
| Username | Password | Role | Purpose |
|----------|----------|------|---------|
| `admin` | `admin` | admin | Full CRUD access |
| `reader` | `reader` | reader | Read-only access |
| `uploader` | `uploader` | uploader | Create and read, no delete |

**Clients (pre-configured):**
| Client ID | Type | Purpose |
|-----------|------|---------|
| `basyx-web-ui` | Public | Web UI login (browser-based auth_code flow) |
| `basyx-admin` | Confidential | API/service access (client_credentials flow) |

**Roles (3 realm roles):**
- `admin`: Full access (CREATE, READ, UPDATE, DELETE, EXECUTE)
- `reader`: Read-only access
- `uploader`: Create and read, but cannot update or delete

### 5. MongoDB (Port 27017)

**What it is:** A NoSQL document database that stores all AAS data persistently.

**Image:** `mongo:7`

**What it does:**
- Stores AAS shells, submodels, and concept descriptions
- Used by both the AAS Environment and the AAS Registry
- Data survives container restarts (stored in Docker/Podman volumes)

**Credentials:** `mongoAdmin` / `mongoPassword`

### 6. PostgreSQL (Keycloak DB)

**What it is:** A relational database that stores Keycloak's configuration and user data.

**Image:** `postgres:16-alpine`

**What it does:**
- Stores Keycloak users, roles, sessions, and tokens
- Only used by Keycloak (not by BaSyx)
- Uses a named Docker volume (`keycloak-db-data`) for persistence

**Credentials:** `keycloak` / `keycloak_db_pass`

---

## File-by-File Walkthrough

### `docker-compose.yml`
The master file that defines all 6 services, their ports, volumes, and dependencies.

Key points:
- **Dependency chain:** MongoDB and Keycloak must start before AAS Environment and Registry
- **Named volume:** `keycloak-db-data` ensures Keycloak's database survives restarts
- **Read-only mounts:** Config files are mounted as `:ro` so containers can't modify them

### `.env`
Secrets and credentials. Loaded automatically by Docker Compose.

**Important:** Change the default passwords before deploying to production!

### `basyx/application.properties`
Configuration for the AAS Environment container.

| Property | Value | Meaning |
|----------|-------|---------|
| `basyx.backend` | `MongoDB` | Use MongoDB for storage |
| `basyx.feature.authorization.enabled` | `true` | Turn on authorization |
| `basyx.feature.authorization.type` | `rbac` | Use Role-Based Access Control |
| `basyx.feature.authorization.jwtBearerTokenProvider` | `keycloak` | Keycloak extracts roles from JWT |
| `basyx.feature.authorization.rbac.file` | `file:/config/rbac_rules.json` | Where the RBAC rules file is |
| `spring.security.oauth2.resourceserver.jwt.jwk-set-uri` | `http://keycloak:8080/...` | Where to validate JWT tokens (internal Docker network URL) |

### `basyx/aas-registry.yml`
Configuration for the AAS Registry container. Same authorization pattern as the AAS Environment.

### `basyx/rbac_rules.json`
Defines what each role can do on the AAS Environment. Each rule has three parts:
- **role**: The name of the role (must match Keycloak role names)
- **action**: What operation is allowed (CREATE, READ, UPDATE, DELETE, EXECUTE)
- **targetInformation**: Which resources the rule applies to

**The 4 `@type` values** (critical for upload to work):
| @type | What it covers |
|-------|---------------|
| `aas-environment` | The combined environment (used for serialization, top-level upload) |
| `aas` | Individual AAS shells |
| `submodel` | Individual submodels (must include `submodelElementIdShortPaths`) |
| `concept-description` | Individual concept descriptions |

**Why 4 types per role?** BaSyx checks authorization at different levels during
different operations. The upload endpoint checks `aas-environment` for the initial
permission, then checks `aas`, `submodel`, and `concept-description` for each
individual item being uploaded.

### `basyx/rbac_rules_registry.json`
Similar to the AAS Environment rules but for the Registry. Uses `@type: "aas-registry"`.

### `basyx-infra.yml`
Tells the Web UI:
- Where the API endpoints are
- How to authenticate (OAuth2 with Keycloak)
- Which Keycloak client to use (`basyx-web-ui`)

### `keycloak/realm-export.json`
A complete Keycloak realm definition that is auto-imported on first startup.
Contains all users, roles, clients, client scopes, and protocol mappers.

The `roles` client scope is critical - it includes a `realm-roles` protocol mapper
that puts the user's roles into the JWT token as `realm_access.roles`. This is
how BaSyx knows what role the user has.

### `aas/` directory
Empty directory mounted into the AAS Environment container. You can pre-load AASX
files here for automatic import on startup (preconfiguration feature).

---

## How Authentication and Authorization Work

### Step 1: User Logs In via Web UI
1. User opens `http://localhost:3000`
2. Web UI redirects to Keycloak: `http://localhost:9096/realms/BaSyx/protocol/openid-connect/auth`
3. User enters credentials (e.g., `admin`/`admin`)
4. Keycloak validates credentials and redirects back to the Web UI with an authorization code
5. Web UI exchanges the code for JWT tokens (access token + refresh token)

### Step 2: JWT Token Contains Roles
The access token looks like this (decoded):
```json
{
  "sub": "ca84d53a-...",
  "iss": "http://localhost:9096/realms/BaSyx",
  "realm_access": {
    "roles": ["admin"]
  },
  "preferred_username": "admin"
}
```

The `realm_access.roles` claim contains the user's Keycloak realm roles.
This is what BaSyx uses to check permissions.

### Step 3: BaSyx Checks RBAC Rules
When a request comes in (e.g., `POST /upload`):
1. BaSyx extracts the JWT token from the `Authorization: Bearer <token>` header
2. It validates the token against Keycloak (checks signature, expiry, issuer)
3. It reads the `realm_access.roles` claim to get the user's roles
4. It loads the RBAC rules from `rbac_rules.json`
5. For each rule, it checks: Does the user have a role that matches? Is the action allowed? Is the target resource covered by the rule?
6. If a matching rule is found, the request proceeds. If not, it returns 403 Forbidden.

### Upload-Specific Behavior
The upload endpoint is special because it processes an AASX/JSON/XML file that may
contain multiple AAS, submodels, and concept descriptions. The authorization checks
happen at multiple levels:

```
1. Upload endpoint check:  role + CREATE + @type:aas-environment
2. For each AAS:           role + CREATE + @type:aas
3. For each Submodel:      role + CREATE + @type:submodel
4. For each ConceptDesc:   role + CREATE + @type:concept-description
```

All checks must pass for the upload to succeed.

---

## Issues We Solved and How

### Issue 1: RBAC Rules Not Mounted into Containers
**Problem:** The RBAC rules file was mounted to a path like `/config/rbac_rules.json`,
but the application tried to load it with `classpath:rbac_rules.json`. Spring's
`classpath:` prefix only looks inside the JAR file, not at mounted host files.

**Solution:** Changed the property from `classpath:rbac_rules.json` to
`file:/config/rbac_rules.json`. The `file:` prefix tells Spring to look at an
absolute filesystem path instead of inside the JAR.

### Issue 2: Upload Returns 403 (Insufficient Permission)
**Problem:** Even with valid JWT tokens and RBAC rules, the upload endpoint returned
HTTP 403.

**Cause 1 - Missing `@type` variations:** Initially, the RBAC rules only had rules
with `@type: "aas-environment"`. But the upload endpoint internally checks permissions
against `@type: "aas"`, `@type: "submodel"`, and `@type: "concept-description"` as well.

**Solution 1:** Added rules for all 4 `@type` values for each role.

**Cause 2 - Missing `submodelElementIdShortPaths`:** The official BaSyx example shows
that `submodel` rules MUST include `"submodelElementIdShortPaths": "*"` in the
targetInformation. Without this field, the RBAC resolver returns null for submodel
operations, causing a NullPointerException.

**Solution 2:** Updated all submodel rules to include `submodelElementIdShortPaths: "*"`.

### Issue 3: Keycloak Realm Import Losing Data on Restart
**Problem:** When Keycloak was restarted, it lost the realm configuration and users
had to be recreated manually.

**Cause:** The PostgreSQL database was not persistent - it was lost when the container
was removed.

**Solution:** Added a named Docker volume `keycloak-db-data` for PostgreSQL data
persistence, and configured Keycloak with `--import-realm` command flag plus
`realm-export.json` for declarative realm setup. The realm auto-imports on first
startup.

### Issue 4: JWT Issuer Mismatch
**Problem:** BaSyx rejected JWT tokens with an "invalid issuer" error.

**Cause:** The JWT token's `iss` claim was `http://localhost:9096/realms/BaSyx`
(because the user's browser connects via `localhost:9096`). But BaSyx's internal
Docker network validated the token against `http://keycloak:8080/...` and the
issuer didn't match.

**Solution:**
1. Set `KC_HOSTNAME=localhost` and `KC_HOSTNAME_PORT=9096` on Keycloak so the
   token's issuer claim is `http://localhost:9096/realms/BaSyx`
2. Added `jwk-set-uri` pointing to the internal Docker address
   (`http://keycloak:8080/...`) for token signature validation
3. The `issuer-uri` stays as `localhost:9096` for the issuer claim check

### Issue 5: Roles Missing from `client_credentials` Tokens
**Problem:** When using the `basyx-admin` client with `client_credentials` grant type,
the JWT token had no roles in `realm_access.roles`.

**Cause:** Keycloak's `client_credentials` flow creates a "service account" that
does NOT automatically get realm roles. The `realm-roles` mapper only maps user
realm roles, and service accounts don't have user-level realm roles by default.

**Workaround:** Use `password` grant (direct access grant) with user credentials
instead of `client_credentials`. This produces tokens with proper `realm_access.roles`
because the user `admin` has the `admin` realm role assigned.

**Current limitation:** The `basyx-admin` client's service account tokens don't
include roles. See "Known Issues" below for fixes.

### Issue 6: Keycloak OOM with 2GB VM
**Problem:** Keycloak crashed with OutOfMemoryError because the Podman VM only had
2GB RAM.

**Solution:** Increased Podman VM memory from 2GB to 4GB.

### Issue 7: Milestone-05 Incompatible with Current Config
**Problem:** Downgrading to `2.0.0-milestone-05` caused the AAS Environment to
connect to `localhost:27017` instead of `mongo:27017`, breaking MongoDB connectivity.

**Cause:** milestone-05 uses different property names for MongoDB configuration
than milestone-13.

**Solution:** Reverted to `2.0.0-milestone-13` which works with the current
`application.properties` format.

---

## Known Issues and Solutions

### Issue A: `client_credentials` Tokens Have No Roles
**Current state:** The `basyx-admin` confidential client's tokens obtained via
`client_credentials` flow have empty `realm_access.roles`.

**Why:** Keycloak service accounts (auto-created for clients with
`serviceAccountsEnabled: true`) do not automatically inherit realm roles.

**Solutions (pick one):**
1. **Use `password` grant** (current workaround): Works for testing but not ideal
   for production service-to-service communication
2. **Assign roles to the service account via Keycloak Admin Console:** Go to
   Clients > basyx-admin > Service Account Roles and assign the `admin` role
3. **Create client-level roles** instead of realm roles, and use
   `resource_access` claim instead of `realm_access`

### Issue B: Upload Overwrites Existing AAS
**Behavior:** When uploading the same AASX file twice, the second upload does NOT
overwrite if the Version and Revision in `AdministrativeInformation` are the same.

**How it works:**
| Scenario | Result |
|----------|--------|
| Same file, same Version/Revision | No overwrite (kept as-is) |
| Same file, no Version/Revision | No overwrite (both null = equal) |
| Newer Version/Revision uploaded | Overwrites the server version |
| Older Version/Revision uploaded | No overwrite |
| Different files, different AAS IDs | Both coexist |

**Solution:** If you need different versions to coexist, bump the Version or
Revision in the AASX file's AdministrativeInformation before uploading. If you
want to upload the same file without any changes, the server will correctly skip it.

### Issue C: Web UI Upload Error
**Current state:** The Web UI shows "Error retrieving AAS page!" during upload.
The API upload works fine via curl.

**Possible causes:**
- The Web UI may send the upload to a different URL than expected
- CORS preflight might fail for the upload endpoint
- The browser token might not have the right scope

**Solution:** Check the browser's DevTools Network tab to see the actual HTTP
response. The fix depends on whether it's a CORS issue, a token issue, or a
request format issue.

---

## Next Steps for Production

### Mandatory (Security)

1. **Change all default passwords** in `.env`:
   - `KC_BOOTSTRAP_ADMIN_PASSWORD` (Keycloak admin)
   - `KC_DB_PASSWORD` (PostgreSQL)
   - `MONGO_PASSWORD` (MongoDB)
   - Change the client secret in `realm-export.json` (`basyx-admin-secret-change-me`)
   - Change user passwords in `realm-export.json`

2. **Enable HTTPS:**
   - Set `KC_HOSTNAME_STRICT_HTTPS=true`
   - Configure TLS certificates for Keycloak (port 9096)
   - Update all `http://` URLs to `https://` in config files
   - Add `spring.security.oauth2.resourceserver.jwt.issuer-uri` with HTTPS

3. **Disable Keycloak dev mode:**
   - Change `command: start-dev --import-realm` to `command: start --import-realm`
   - Set `KC_HTTP_ENABLED=false` (use a reverse proxy instead)
   - Set `KC_PROXY_HEADERS=xforwarded` if using a reverse proxy

4. **Fix `client_credentials` token roles:**
   - Assign roles to the `basyx-admin` service account in Keycloak
   - Or create a dedicated API client with proper role mappings

5. **Enable MongoDB authentication:**
   - Currently MongoDB has auth but the connection string uses `admin` database
   - For production, create dedicated databases with limited permissions

### Mandatory (Reliability)

6. **Use named volumes for MongoDB:**
   - Add a named volume for MongoDB data (currently uses default anonymous volume):
   ```yaml
   volumes:
     mongo-data:
   # In the mongo service:
     volumes:
       - mongo-data:/data/db
   ```

7. **Add health checks to more services:**
   - The AAS Environment and Registry don't have health checks
   - Add `healthcheck` to `aas-environment` and `aas-registry` services

8. **Resource limits:**
   - Add `deploy.resources.limits` to prevent containers from consuming all memory
   - Recommendation: AAS Environment needs at least 1GB, Keycloak needs at least 1GB

9. **Use specific image tags:**
   - `eclipsebasyx/aas-gui:latest` pulls the latest tag which can change
   - Pin to a specific version for reproducibility

### Optional (Enhanced Features)

10. **Add an AAS Discovery Service:**
    - Image: `eclipsebasyx/aas-discovery:2.0.0-milestone-13`
    - Provides shell lookup across multiple AAS Environments
    - Needs its own RBAC rules file

11. **Add a Submodel Registry:**
    - Image: `eclipsebasyx/submodel-registry-log-mongodb:2.0.0-milestone-13`
    - Separate registry for submodels (the current setup only has AAS Registry)

12. **Add a Reverse Proxy (Nginx/Traefik):**
    - Terminate TLS
    - Route traffic to the right service
    - Add rate limiting and request size limits

13. **Pre-load AASX files:**
    - Place AASX files in the `aas/` directory
    - Configure `basyx.environment` in `application.properties`:
    ```
    basyx.environment=file:/application/aas
    ```
    - AAS files are loaded automatically on startup

14. **Add monitoring:**
    - BaSyx supports Spring Actuator endpoints (`/actuator/health`, `/actuator/info`)
    - Integrate with Prometheus/Grafana for dashboards
    - Add centralized logging (ELK stack or Loki)

15. **Backup strategy:**
    - Regular MongoDB dumps: `mongodump`
    - PostgreSQL dumps for Keycloak data
    - Back up the `realm-export.json` and all config files

16. **Multiple environments:**
    - Use separate `docker-compose.override.yml` files for dev/staging/production
    - Use Docker Compose profiles to optionally include services

---

## Quick Reference: Ports

| Service | Internal Port | External Port | URL |
|---------|--------------|---------------|-----|
| AAS Web UI | 3000 | 3000 | http://localhost:3000 |
| AAS Environment | 8081 | 8081 | http://localhost:8081 |
| AAS Registry | 8080 | 8083 | http://localhost:8083 |
| Keycloak | 8080 | 9096 | http://localhost:9096 |
| MongoDB | 27017 | 27017 | localhost:27017 |

## Quick Reference: Test Credentials

| User | Password | Role | Use for |
|------|----------|------|---------|
| admin | admin | admin | Full access (upload, delete, everything) |
| reader | reader | reader | View-only access |
| uploader | uploader | uploader | Upload and read only |

## Quick Reference: Test Upload via curl

```bash
# Get a token
TOKEN=$(curl -s -X POST "http://localhost:9096/realms/BaSyx/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=basyx-admin" \
  -d "client_secret=basyx-admin-secret-change-me" \
  -d "username=admin" \
  -d "password=admin" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Upload an AASX file
curl -X POST "http://localhost:8081/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@your-file.aasx"

# List all AAS
curl -H "Authorization: Bearer $TOKEN" http://localhost:8081/shells
```
