# Design Choices — Exhaustive Defence

Every architectural decision in this BaSyx setup, why it was made, what the alternatives are, and what is mandatory vs optional.

---

## Table of Contents

1. [Summary: Mandatory vs Optional](#summary-mandatory-vs-optional)
2. [Component Choices](#component-choices)
   - [AAS Server Implementation: Java vs Go](#1-aas-server-implementation-java-vs-go)
   - [Identity Provider: Why Keycloak](#2-identity-provider-why-keycloak)
   - [Database: MongoDB vs PostgreSQL vs InMemory](#3-database-mongodb-vs-postgresql-vs-inmemory)
3. [Protocol Choices](#protocol-choices)
   - [OAuth2 + OpenID Connect (OIDC)](#4-oauth2--openid-connect-oidc)
   - [Authorization Code Flow + PKCE](#5-authorization-code-flow--pkce)
   - [JWT as the token format](#6-jwt-as-the-token-format)
4. [Access Control Choices](#access-control-choices)
   - [RBAC vs ABAC vs ACL](#7-rbac-vs-abac-vs-acl)
   - [Keycloak as JWT provider (hardcoded)](#8-keycloak-as-jwt-provider-hardcoded)
   - [RBAC rules file format and storage](#9-rbac-rules-file-format-and-storage)
5. [Infrastructure Choices](#infrastructure-choices)
   - [nginx as reverse proxy](#10-nginx-as-reverse-proxy)
   - [HTTPS / TLS termination](#11-https--tls-termination)
   - [Self-signed certificate vs CA-signed](#12-self-signed-certificate-vs-ca-signed)
   - [Path-based routing vs separate ports](#13-path-based-routing-vs-separate-ports)
   - [Docker Compose vs Podman](#14-docker-compose-vs-podman)
6. [Configuration Choices](#configuration-choices)
   - [Realm import via JSON file](#15-realm-import-via-json-file)
   - [Client design: public vs confidential](#16-client-design-public-vs-confidential)
   - [Token lifespan settings](#17-token-lifespan-settings)
   - [Registry integration](#18-registry-integration)
   - [CORS configuration](#19-cors-configuration)
7. [What Could Be Different](#what-could-be-different)

---

## Summary: Mandatory vs Optional

### Mandatory (you have no choice or very limited choice)

| Decision | Why mandatory | Could it be different? |
|----------|--------------|----------------------|
| **Keycloak as JWT provider** | BaSyx Java V2 SDK hardcodes `KeycloakRoleAuthenticator` — only Keycloak's `realm_access.roles` claim format is supported out of the box | Only by writing custom Java code |
| **RBAC as access control model** | BaSyx V2 only implements RBAC — no ABAC, ACL, or other models in the Java SDK | Only in BaSyx Go components (which support ABAC) |
| **OpenID Connect for Web UI auth** | The AAS Web UI uses OIDC discovery to find endpoints — any IDP must be OIDC-compatible | No, OIDC is required by the SPA |
| **OAuth2 Authorization Code flow** | PKCE + auth_code is the only flow the Web UI supports for browser-based login | Client credentials is also possible but not for browser users |
| **HTTPS for OAuth2** | PKCE requires `crypto.subtle` which only works in secure contexts (HTTPS or localhost) | Only if accessing from localhost |

### Optional (you have alternatives)

| Decision | What was chosen | Alternatives |
|----------|----------------|-------------|
| Java SDK vs Go SDK | Java (`eclipsebasyx/aas-environment:2.0.0-milestone-13`) | Go components (support ABAC, use PostgreSQL) |
| Identity provider brand | Keycloak | Azure AD, Auth0, Okta, Google, etc. (for Web UI only) |
| Database for AAS data | MongoDB 7 | InMemory (dev only), or Go components use PostgreSQL |
| Database for Keycloak | PostgreSQL 16 | MySQL/MariaDB, H2 (dev only) |
| Reverse proxy | nginx | Traefik, Caddy, HAProxy, or no proxy (direct access) |
| Certificate authority | Self-signed | Let's Encrypt, corporate CA |
| RBAC rules storage | JSON file on disk | Submodel-based storage (in AAS Repository) |
| Event sink | Logs only | Apache Kafka (available in BaSyx images) |

---

## Component Choices

### 1. AAS Server Implementation: Java vs Go

**Chosen:** BaSyx Java SDK (v2.0.0-milestone-13)

**Why:** The Java SDK is the original and most complete implementation. It has:
- Full AAS Environment (aggregates AAS + Submodel + CD repositories)
- Upload endpoint for AASX/JSON/XML files
- RBAC authorization with Keycloak
- Registry integration
- MongoDB persistence
- Docker images on DockerHub (`eclipsebasyx/*`)

**Alternative — BaSyx Go components:**
The Go implementation (`basyx-go-components`) offers:
- PostgreSQL instead of MongoDB
- **ABAC (Attribute-Based Access Control)** instead of RBAC
- OIDC authentication via trustlist (supports any OIDC provider natively)
- Potentially better performance
- But: newer, less mature, different configuration model

**Key difference in authorization:**

| | Java SDK (this setup) | Go SDK |
|---|---|---|
| Access control model | RBAC only | ABAC (attribute-based) |
| JWT provider | Keycloak only (hardcoded) | Any OIDC provider (via trustlist) |
| Role extraction | `realm_access.roles` claim (Keycloak format) | Configurable claim mappings |
| Policy storage | JSON file or Submodel-based | Database-backed with runtime management API |

**Verdict:** Java SDK is mandatory if you want the AAS Environment component with AASX upload support and the mature ecosystem. Go components are mainly registries/repositories without the aggregated environment.

---

### 2. Identity Provider: Why Keycloak

**Chosen:** Keycloak (open-source, self-hosted)

**Is Keycloak the only option?** It depends on which component you're talking about:

#### For the AAS Backend (Java SDK): Keycloak is effectively mandatory

The BaSyx Java V2 documentation states explicitly across ALL component authorization pages:

> "Only Role Based Access Control (RBAC) is supported as authorization type as of now, also **Keycloak is the only JWT token provider supported now** and it is also a default provider."

This is because the role extraction logic is hardcoded to Keycloak's JWT format:

```
// BaSyx source code — KeycloakRoleAuthenticator
// Extracts roles from: realm_access.roles
// This is Keycloak-specific. Other providers put roles in different claims:
//   Auth0:   permissions, roles
//   Okta:    roles, groups
//   Azure AD: roles, wids
//   Google:   doesn't natively support RBAC claims
```

The configuration property `basyx.feature.authorization.jwtBearerTokenProvider=keycloak` is not a URL or endpoint — it's a **Java class name alias** that selects `KeycloakRoleAuthenticator`.

**However**, there is an escape hatch in the V1 SDK and in the source code:

```
// V1 SDK allows custom providers via:
authorization.strategy.jwtBearerTokenAuthenticationConfigurationProvider = your.custom.Class
authorization.strategy.simpleRbac.roleAuthenticator = your.custom.RoleAuthenticator
```

In V2, the same extensibility exists but requires building a custom Docker image from the BaSyx source code. The off-the-shelf Docker images only support `keycloak`.

#### For the Web UI: Any OIDC provider works

The AAS Web UI (`eclipsebasyx/aas-gui`) is a separate frontend that supports **any OAuth2/OIDC provider**:

> "The Web UI supports any OAuth2-compatible identity provider (IDP), including Keycloak, Azure Active Directory, Auth0, Okta, Google Identity Platform, Amazon Cognito, or any custom OAuth2/OIDC compliant identity provider."

This works because the Web UI only needs the OIDC discovery endpoint (`/.well-known/openid-configuration`) to find the authorization and token endpoints. It doesn't care about the role format — it just passes the JWT through to the backend.

**Summary:**

| Component | Can use non-Keycloak IDP? | Why |
|-----------|--------------------------|-----|
| AAS Web UI | Yes (any OIDC provider) | Only needs discovery endpoint |
| AAS Environment (Java) | **No** (Keycloak only) | Role extraction hardcoded to `realm_access.roles` |
| AAS Registry (Java) | **No** (Keycloak only) | Same reason |
| AAS Repository (Java) | **No** (Keycloak only) | Same reason |
| BaSyx Go components | Yes (any OIDC provider) | Uses configurable claim mappings |

**Why Keycloak specifically and not another provider?**

1. **`realm_access.roles` format**: Keycloak puts realm-level roles in a `realm_access.roles` array claim. This is a Keycloak-specific convention. BaSyx's `KeycloakRoleAuthenticator` reads exactly this claim path. (See [Where is `realm_access.roles` connected?](#where-is-realm_access.roles-connected) below.)

2. **Realm concept**: Keycloak's "realm" maps naturally to a BaSyx deployment. One realm = one AAS deployment with its own users, roles, and clients.

3. **Free and self-hosted**: Keycloak is open-source (Apache 2.0) and runs as a single Docker container. No license costs, no cloud dependency.

4. **Eclipse Foundation alignment**: BaSyx is an Eclipse Foundation project. Keycloak is also an Eclipse Foundation project (originally Red Hat). They share the same ecosystem.

5. **Feature completeness**: Keycloak provides everything BaSyx needs: realms, roles, clients (public + confidential), OIDC discovery, JWKS endpoint, user management, and an admin console.

#### Where is `realm_access.roles` connected?

The chain from JWT to RBAC decision spans 4 files:

```
realm-export.json:292-306
  "name": "realm-roles",
  "protocolMapper": "oidc-usermodel-realm-role-mapper",
  "config": {
    "claim.name": "realm_access.roles",       ← THIS puts roles in the JWT
    "access.token.claim": "true"
  }
        │
        │ Keycloak generates JWT with this claim
        ▼
JWT payload:
  { "realm_access": { "roles": ["admin"] } }
        │
        │ Sent in Authorization: Bearer header
        ▼
application.properties:24
  basyx.feature.authorization.jwtBearerTokenProvider=keycloak
        │
        │ BaSyx resolves "keycloak" to a Java class
        ▼
BaSyx Java source code (KeycloakRoleAuthenticator.java):
  // Reads: jwt.get("realm_access").getAsJsonObject().getAsJsonArray("roles")
  // This is the hardcoded Keycloak-specific claim path
        │
        │ Returns list of roles
        ▼
rbac_rules.json
  // Matches roles against rules to allow/deny the operation
```

The `realm_access.roles` claim path is hardcoded in BaSyx's `KeycloakRoleAuthenticator` Java class. If you used Azure AD (which puts roles in the `roles` claim), this code would not find them. You would need a custom `IRoleAuthenticator` that reads from `roles` instead of `realm_access.roles`.

---

### 3. Database: MongoDB vs PostgreSQL vs InMemory

**Chosen:** MongoDB 7 for AAS data, PostgreSQL 16 for Keycloak

**Why two different databases?**

They serve completely separate systems:

| Database | Used by | Stores | Why this engine |
|----------|---------|--------|----------------|
| MongoDB 7 | AAS Environment + AAS Registry | AAS shells, submodels, concept descriptions, shell descriptors | BaSyx Java SDK was designed around MongoDB's document model (AAS data is naturally hierarchical/JSON-like) |
| PostgreSQL 16 | Keycloak | Users, roles, clients, sessions, tokens | Keycloak requires a relational database (MongoDB support was removed years ago) |

**Alternatives for AAS data:**

| Backend | When to use | Limitations |
|---------|-------------|-------------|
| **InMemory** | Development, testing, demos | Data lost on container restart. Default if `basyx.backend` not set. |
| **MongoDB** | Production, this setup | Requires MongoDB container. Most tested backend. |
| **PostgreSQL** (Go only) | If using BaSyx Go components | Not available in Java SDK |

**Why MongoDB for AAS data?**
- AAS shells, submodels, and concept descriptions are complex nested JSON structures
- MongoDB's document model maps naturally to AAS data (no need for JOIN-heavy relational schemas)
- The BaSyx Java SDK was built with MongoDB as the primary persistent backend
- Collection names are configurable: `basyx.aasrepository.mongodb.collectionName=aas-repo`

**Why PostgreSQL for Keycloak?**
- Keycloak dropped MongoDB support years ago
- PostgreSQL is the recommended production database for Keycloak
- MySQL/MariaDB are also supported alternatives
- H2 is available for development only (data not persistent)

**Production note:** MongoDB currently has **no named volume** in this setup — the `mongo` service in `docker-compose.yml` doesn't declare a named volume for `/data/db`. Docker creates an anonymous volume automatically, but anonymous volumes can be removed by `docker compose down -v`. For production, a named volume (`mongo-data:/data/db`) is mandatory for data persistence.

---

## Protocol Choices

### 4. OAuth2 + OpenID Connect (OIDC)

**Chosen:** OAuth2 with OpenID Connect

**Why OAuth2?**
- Industry standard for delegated authorization
- Separates authentication (who are you?) from authorization (what can you do?)
- Supported by all major identity providers
- Spring Security (used by BaSyx Java) has native OAuth2 Resource Server support

**Why OpenID Connect (OIDC)?**
- OIDC is a thin layer on top of OAuth2 that adds:
  - **ID tokens** (proof of identity)
  - **Discovery endpoint** (`/.well-known/openid-configuration`) — the Web UI uses this to auto-configure itself
  - **Standard scopes** (`openid`, `profile`, `email`, `roles`)
  - **Standard claims** (`sub`, `iss`, `exp`, `preferred_username`)
- Without OIDC, the Web UI would need hard-coded endpoint URLs instead of discovering them

**Alternatives considered:**

| Alternative | Why not used |
|-------------|-------------|
| **SAML 2.0** | Older protocol, XML-based, more complex. Keycloak supports it but OAuth2/OIDC is simpler for browser SPAs. |
| **API Keys** | No user identity, no roles, no expiration. Not suitable for user-facing applications. |
| **Session cookies** | Tightly couples client and server. Doesn't work well with microservices (multiple backends). |
| **mTLS** | Requires certificate management per client. Overkill for web browser clients. |

---

### 5. Authorization Code Flow + PKCE

**Chosen:** OAuth2 Authorization Code Flow with Proof Key for Code Exchange (PKCE)

**Why this flow?**

The Authorization Code flow is the most secure option for browser-based applications:

1. User is redirected to the IDP (Keycloak) for login
2. IDP issues an authorization code
3. SPA exchanges code for tokens (with PKCE proof)
4. Tokens never appear in the browser URL bar

**Why PKCE?**
- Prevents authorization code interception attacks
- Required by OAuth2 spec for public clients (SPAs, mobile apps)
- Requires `crypto.subtle` -> requires HTTPS -> requires nginx with TLS

**Why not other flows?**

| Flow | Why not for this use case |
|------|--------------------------|
| **Implicit** | Deprecated by OAuth 2.1. Tokens exposed in URL fragment. |
| **Client Credentials** | Machine-to-machine only. No user login. Cannot be used in browser. |
| **Resource Owner Password** | Exposes user credentials to the client. Deprecated by OAuth 2.1. |
| **Device Code** | For input-constrained devices (smart TVs, CLI). Not for browsers. |

**Configuration source:**
- `basyx-infra.yml:19` -> `flow: auth_code`
- `realm-export.json:29` -> `standardFlowEnabled: true` (enables auth code for `basyx-web-ui` client)
- `realm-export.json:30` -> `directAccessGrantsEnabled: false` (disables password login for `basyx-web-ui`)

---

### 6. JWT as the token format

**Chosen:** JWT (JSON Web Token) as the access token format

**Why JWT?**
- **Self-contained**: The token carries all needed info (user, roles, expiry) — no database lookup needed for each request
- **Stateless validation**: The AAS Environment validates the JWT signature using Keycloak's public keys (JWKS endpoint) without calling Keycloak on every request
- **Standard format**: Any Spring Security OAuth2 Resource Server can validate JWTs out of the box
- **Cross-service**: The same JWT works for AAS Environment, AAS Registry, and any other BaSyx component

**How validation works without calling Keycloak:**

```
1. AAS Environment starts -> fetches Keycloak's public keys from JWKS endpoint
   application.properties:32
     jwk-set-uri=http://keycloak:8080/realms/BaSyx/protocol/openid-connect/certs

2. Keys are cached in memory

3. Each request -> AAS Environment verifies JWT signature locally using cached keys

4. Periodically refreshes keys (if Keycloak rotates them)
```

**Alternative — Opaque tokens:**
Opaque tokens are random strings that require a call to the IDP to introspect (validate + read info). This would add latency to every API call and create a hard dependency on Keycloak being available. JWT avoids this.

---

## Access Control Choices

### 7. RBAC vs ABAC vs ACL

**Chosen:** RBAC (Role-Based Access Control)

**Why RBAC?**

In the Java SDK, this is the **only option**:

> "Only Role Based Access Control (RBAC) is supported as authorization type as of now."

RBAC maps naturally to the AAS use case:
- Different user types (admin, reader, uploader) need different permission levels
- Permissions are coarse-grained (CRUD on AAS, submodels, concept descriptions)
- Roles are assigned in Keycloak and embedded in the JWT

**What RBAC looks like in this setup:**

```
User "admin"   -> has role "admin"   -> can CREATE, READ, UPDATE, DELETE, EXECUTE
User "reader"  -> has role "reader"  -> can READ only
User "uploader" -> has role "uploader" -> can CREATE, READ, UPDATE (no DELETE)
```

**Alternatives (not available in Java SDK):**

| Model | What it is | Available in |
|-------|-----------|-------------|
| **ABAC** (Attribute-Based) | Decisions based on attributes of subject, resource, action, and environment | BaSyx Go components only |
| **ACL** (Access Control Lists) | Per-resource permissions for specific users | Not implemented in BaSyx |
| **PBAC** (Policy-Based) | Complex rules with conditions | Not implemented in BaSyx |

**The Go components support ABAC:**
```
// BaSyx Go configuration
abac.enabled: true
abac.modelPath: config/access_rules/access-rules.json
```
ABAC allows policies like "user can only access AAS shells created in the last 30 days" or "user from department X can only read submodels tagged with X."

---

### 8. Keycloak as JWT provider (hardcoded)

**Chosen:** `jwtBearerTokenProvider=keycloak`

**Why it's hardcoded:**

The value `keycloak` is not a URL or config string — it's an alias for a Java class:

```
// BaSyx source code:
// jwtBearerTokenProvider=keycloak
// resolves to:
KeycloakRoleAuthenticator
// which reads roles from:
JWT.get("realm_access").get("roles")
```

This is a **code-level dependency**, not a configuration-level one. The `realm_access.roles` claim path is specific to Keycloak. Other providers use different claim structures:

| Provider | Where roles live in JWT |
|----------|------------------------|
| Keycloak | `realm_access.roles` |
| Azure AD | `roles` or `wids` (well-known IDs) |
| Auth0 | `permissions` or custom namespace claims |
| Okta | `groups` or `roles` claim |
| Google | No native role claims |

**Can you replace Keycloak?**

Yes, but only by:
1. **Building a custom Docker image** from BaSyx source
2. **Implementing a custom `IRoleAuthenticator`** that reads roles from your provider's claim format
3. **Registering it** via `basyx.feature.authorization.jwtBearerTokenProvider=com.your.CustomAuthenticator`

This is documented in the V1 SDK's extensibility model and applies to V2 as well, but the off-the-shelf Docker images only ship with `KeycloakRoleAuthenticator`.

---

### 9. RBAC rules file format and storage

**Chosen:** JSON file on disk (`file:/config/rbac_rules.json`)

**Why a JSON file?**
- Simple to understand and edit
- Version-controllable (stored in git)
- Loaded once at startup, kept in memory (fast)

**Why `file:` prefix instead of `classpath:`?**
- `classpath:` looks inside the Java JAR file (not accessible in Docker)
- `file:` looks at an absolute path on the filesystem (works with Docker volume mounts)
- The Docker volume mount (`./basyx/rbac_rules.json:/config/rbac_rules.json:ro`) places the file at `/config/rbac_rules.json` inside the container

**Alternatives for RBAC rules storage:**

| Storage | When to use | How to enable |
|---------|-------------|--------------|
| **JSON file** (this setup) | Simple deployments, small number of rules | `basyx.feature.authorization.rbac.file=file:/config/rbac_rules.json` |
| **Submodel-based** | Dynamic rules, rules that need to be managed via API | `basyx.feature.authorization.rules.backend=Submodel` + configure a Submodel Repository endpoint |

The Submodel-based option stores RBAC rules inside an AAS Submodel in a Submodel Repository, allowing rules to be read/updated via the standard Submodel API. This is useful for large-scale deployments where rules change frequently and need to be managed programmatically.

---

## Infrastructure Choices

### 10. nginx as reverse proxy

**Chosen:** nginx (alpine image)

**Why nginx?**
- Lightweight, battle-tested, minimal resource usage
- Alpine image is ~20MB
- Native SSL termination
- Path-based routing via regex patterns
- Passes `X-Forwarded-*` headers (required for Keycloak to generate correct external URLs)

**Alternatives:**

| Proxy | Pros | Cons |
|-------|------|------|
| **nginx** (chosen) | Lightweight, widely documented, Alpine image minimal | Manual config, no auto-discovery |
| **Traefik** | Auto-discovery of Docker services, Let's Encrypt integration | Heavier, more complex config for simple setups |
| **Caddy** | Automatic HTTPS, simpler config | Less ecosystem support in industrial contexts |
| **HAProxy** | Very high performance, advanced load balancing | Overkill for a single-server setup |
| **No proxy** | Simpler | Cannot do HTTPS termination, path-based routing, or header manipulation. PKCE won't work without HTTPS. |

**Why not skip the proxy?**
Without nginx:
1. No HTTPS -> no `crypto.subtle` -> OAuth2 PKCE fails
2. SPA and API on different ports -> CORS issues
3. Keycloak generates `http://` URLs instead of `https://`

---

### 11. HTTPS / TLS termination

**Chosen:** TLS termination at nginx (ports 8443, 9443)

**Why is HTTPS mandatory?**

The OAuth2 PKCE flow requires `crypto.subtle` (for SHA-256 hashing of the code verifier). Browsers only enable `crypto.subtle` in **secure contexts**:

| Context | `crypto.subtle` available? |
|---------|--------------------------|
| `https://` (any port) | Yes |
| `http://localhost` | Yes |
| `http://192.168.56.212` | **No** |
| `http://127.0.0.1` | Yes |

Since this setup runs on a network machine (not localhost), HTTPS is the only option.

**Why ports 8443/9443 instead of 443?**
- Docker runs in **rootless mode** on this machine
- Rootless Docker cannot bind ports below 1024
- Port 443 requires root privileges
- 8443 and 9443 are the conventional alternatives

---

### 12. Self-signed certificate vs CA-signed

**Chosen:** Self-signed certificate

**Why self-signed?**
- No dependency on external CA
- Works offline / in air-gapped networks
- Instant generation (no domain validation wait)
- Sufficient for development and internal network use

**Limitation:** Browsers show a security warning. Users must click "Advanced" -> "Proceed" on first visit. After accepting, the certificate is trusted for that browser session.

**When to use CA-signed:**
- Production deployments
- When users should not see any warnings
- When integrating with corporate identity systems
- When using Let's Encrypt (requires public DNS + port 80 reachable from internet)

**Certificate generation:**
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/server.key \
  -out nginx/certs/server.crt \
  -subj "/CN=192.168.56.212"
```

---

### 13. Path-based routing vs separate ports

**Chosen:** Path-based routing on a single port (8443)

All browser traffic goes through `https://192.168.56.212:8443`:
- `https://192.168.56.212:8443/` -> AAS Web UI (SPA)
- `https://192.168.56.212:8443/shells` -> AAS Environment API
- `https://192.168.56.212:8443/submodels` -> AAS Environment API
- `https://192.168.56.212:8443/concept-descriptions` -> AAS Environment API

**Why path-based instead of separate ports?**

| Approach | Pros | Cons |
|----------|------|------|
| **Path-based** (chosen) | Same origin for SPA + API -> no CORS issues, no cert-per-port issues | nginx must parse path patterns |
| **Separate ports** (e.g., :3000 for SPA, :8081 for API) | Simpler nginx config | Cross-origin requests -> CORS headers needed, browser may block mixed-content, each port needs its own TLS cert |

**The key problem with separate ports:**
The browser would talk to two different origins (`https://host:3000` and `https://host:8081`). This triggers:
1. CORS preflight requests
2. Each port needs a valid TLS certificate
3. Cookie-based sessions don't work across origins

With path-based routing, everything is same-origin (`https://host:8443`), so none of these issues apply.

---

### 14. Docker Compose vs Podman

**Chosen:** Docker Compose (with Podman backend on this machine)

**Note from ARCHITECTURE.md:**
> "Use `podman compose` with the external `docker-compose` provider (Docker Desktop has a bad CPU type on this machine)."

The machine uses Podman (not Docker Desktop) because Docker Desktop requires an Intel/AMD CPU but this machine has an ARM CPU (Apple Silicon). Podman handles the emulation transparently.

**Alternatives:**
- Docker Desktop (if available and compatible)
- Kubernetes (for production scale)
- Podman standalone (without compose)

---

## Configuration Choices

### 15. Realm import via JSON file

**Chosen:** `realm-export.json` auto-imported via `--import-realm`

**Why this approach?**
- **Declarative**: The entire Keycloak realm (users, roles, clients, scopes) is defined in a single file
- **Reproducible**: The same file produces the same realm every time
- **Version-controlled**: Stored in git, changes are tracked
- **No manual setup**: No need to click through Keycloak admin console

**Limitation:** The `--import-realm` flag only imports on **first startup**. If the realm already exists in PostgreSQL, the import is skipped. To update the realm, you must either:
1. Delete the PostgreSQL volume and restart
2. Import via Keycloak admin console or API

**Alternative:** Configure everything manually via Keycloak Admin Console (`https://keycloak:9443/admin`). More flexible but not reproducible.

---

### 16. Client design: public vs confidential

**Two clients defined in realm-export.json:**

#### `basyx-web-ui` (Public client)

```json
{
  "clientId": "basyx-web-ui",
  "publicClient": true,
  "standardFlowEnabled": true,
  "directAccessGrantsEnabled": false,
  "serviceAccountsEnabled": false
}
```

**Why public?**
- The SPA runs in the browser — you cannot hide a client secret in browser JavaScript
- Anyone can view the page source and extract any embedded secret
- PKCE replaces the need for a client secret (proves the client identity cryptographically)

**Why `directAccessGrantsEnabled: false`?**
- Prevents the password grant flow (username+password sent directly to token endpoint)
- Forces all authentication through the browser redirect flow (more secure)

#### `basyx-admin` (Confidential client)

```json
{
  "clientId": "basyx-admin",
  "publicClient": false,
  "standardFlowEnabled": false,
  "directAccessGrantsEnabled": true,
  "serviceAccountsEnabled": true,
  "secret": "basyx-admin-secret-change-me"
}
```

**Why confidential?**
- Used for server-to-server calls (curl, scripts, preconfiguration)
- The secret never leaves the server
- Supports `client_credentials` and `password` grant flows

**Why `standardFlowEnabled: false`?**
- This client is not for browser login — no redirect flow needed

---

### 17. Token lifespan settings

```json
{
  "accessTokenLifespan": 300,        // 5 minutes
  "ssoSessionIdleTimeout": 1800,     // 30 minutes
  "ssoSessionMaxLifespan": 36000     // 10 hours
}
```

**Why 5-minute access tokens?**
- Short-lived tokens limit the damage if stolen
- The SPA automatically refreshes tokens using the refresh token
- Users don't need to re-login for 30 minutes (idle) or 10 hours (max)

**Trade-offs:**

| Shorter lifespan | Longer lifespan |
|-----------------|----------------|
| More secure (less time for stolen token) | Less secure (longer window for abuse) |
| More refresh calls -> more load on Keycloak | Fewer refresh calls |
| Better for high-security environments | Better for user experience |

---

### 18. Registry integration

**Chosen:** Enabled (`basyx.aasrepository.feature.registryintegration=http://aas-registry:8080`)

**What it does:**
When a shell is created in the AAS Environment, it also registers a **shell descriptor** in the AAS Registry. This allows other systems to discover shells across multiple AAS Environments.

**Why enable it?**
- Enables discovery: other BaSyx installations can find your AAS shells
- Required for multi-server deployments
- Standard AAS architecture pattern

**Why it might cause issues:**
- If the AAS Registry is down or unreachable, shell creation might fail or produce errors
- Registry registration uses the `basyx.externalurl` which must be reachable from the registry container
- The AAS Registry has authorization **disabled** in this setup, which may cause inconsistent behavior

**Alternative:** Disable registry integration if you only have one AAS Environment and don't need cross-server discovery.

---

### 19. CORS configuration

```
basyx.cors.allowed-origins=https://${HOST_IP}:8443
basyx.cors.allowed-methods=GET,POST,PUT,PATCH,DELETE,OPTIONS,HEAD
basyx.cors.allowed-headers=*
basyx.cors.allow-credentials=true
```

**Why CORS is configured even though path-based routing makes everything same-origin?**

1. **Safety net**: If someone accesses the AAS Environment directly on port 8081 (bypassing nginx), CORS headers are still correct
2. **Direct API access**: Developers may test with `curl` or Postman against `:8081` directly
3. **Future-proofing**: If the architecture changes (e.g., a separate frontend on a different port)

**The `allow-credentials: true` setting** is needed because the browser sends cookies and Authorization headers with requests. Without this, the browser would strip authentication headers on cross-origin requests.

---

## What Could Be Different

### If you used BaSyx Go components instead:

| Aspect | Java SDK (current) | Go SDK |
|--------|-------------------|--------|
| Database | MongoDB | PostgreSQL |
| Access control | RBAC | ABAC |
| JWT provider | Keycloak only | Any OIDC provider |
| AAS Environment | Yes (aggregated) | Separate repositories |
| AASX upload | Yes | Separate AASX file server |
| Maturity | High (years of development) | Lower (newer) |

### If you didn't use a reverse proxy:

| Aspect | With nginx | Without nginx |
|--------|-----------|--------------|
| HTTPS | Yes | No |
| OAuth2 PKCE | Works | Fails (no `crypto.subtle`) |
| Path-based routing | Yes | No |
| Mixed-content issues | None | Possible |
| TLS cert management | Single cert | Multiple certs (one per port) |

### If you used a cloud IDP (e.g., Azure AD):

| Aspect | Keycloak (current) | Azure AD |
|--------|-------------------|----------|
| Hosting | Self-hosted | Microsoft cloud |
| Cost | Free | Free tier + paid tiers |
| AAS backend compatibility | Yes (native) | No (custom code needed) |
| Web UI compatibility | Yes | Yes (any OIDC) |
| Role format | `realm_access.roles` | `roles` or `wids` claim |
| Offline operation | Yes | No (requires internet) |
| Enterprise integration | Manual | Native AD/LDAP sync |

---

## Remaining Questions

### Kafka Event Sink — Use Case

BaSyx Java images bundle Apache Kafka. The `aas-environment` can publish AAS change events (shell created, submodel updated, etc.) to Kafka topics. In this setup, Kafka is **not enabled** — event consumption is set to `logs` only.

**When to enable Kafka:**
- **Event-driven integration**: Other systems (ERP, MES, PLM) need to react to AAS changes in real time
- **Audit trail**: Every AAS mutation is recorded as an immutable event
- **Multi-system synchronization**: Multiple consumers process the same AAS changes independently
- **Webhook-like triggers**: External systems subscribe to topics and perform actions (e.g., "when a shell is created, register it in the company catalog")

**Why not enabled here:**
- Single-server development setup — no external consumers exist
- Adds operational complexity (Kafka broker, topic management, consumer groups)
- Logs are sufficient for debugging

To enable, add a Kafka service to `docker-compose.yml` and set `basyx.feature.eventing.sink=kafka` with the broker URL in `application.properties`.

---

### Submodel-Based RBAC — Benefit

The RBAC rules in this setup are stored in a **JSON file on disk** (`rbac_rules.json`). BaSyx also supports storing rules inside an AAS Submodel in a Submodel Repository.

**Why file-based was chosen:**
- Simpler to understand and debug
- Version-controllable (git)
- Loaded once at startup, kept in memory (fast)
- No additional repository dependency

**When Submodel-based is better:**
- **Dynamic rule updates**: Rules can be changed via the Submodel API without restarting the AAS Environment
- **Large-scale deployments**: Hundreds of roles/rules that change frequently
- **Programmatic management**: Rules are managed by other AAS components (e.g., an admin dashboard that modifies rules via the Submodel API)
- **Multi-tenancy**: Different rule sets per tenant, stored as separate Submodels

**How it works:**
Set `basyx.feature.authorization.rules.backend=Submodel` and point to a Submodel Repository endpoint. The AAS Environment reads rules from a Submodel (identified by a specific Submodel ID) at startup and periodically refreshes.

---

## Decision Tree

```
Do you need authentication?
├── No -> Disable authorization (basyx.feature.authorization.enabled=false)
│        ⚠️ Not recommended for anything beyond local development
│
└── Yes
    ├── Are you using BaSyx Java SDK (off-the-shelf Docker images)?
    │   ├── Yes -> You MUST use Keycloak
    │   │   ├── Is this a browser-based deployment?
    │   │   │   ├── Yes -> You NEED HTTPS (nginx + TLS)
    │   │   │   │   ├── Public network -> self-signed or CA cert
    │   │   │   │   └── Localhost only -> HTTP works (crypto.subtle available)
    │   │   │   └── No (API-only) -> HTTP may work depending on setup
    │   │   └── Do you need RBAC rules to be managed dynamically?
    │   │       ├── Yes -> Use Submodel-based RBAC storage
    │   │       └── No -> Use JSON file (simpler)
    │   │
    │   └── No (BaSyx Go components)
    │       └── You can use ANY OIDC provider
    │           ├── Configure trustlist.json with your IDP's issuer URL
    │           └── Configure claim mappings for your provider's role format
    │
    └── What access control model?
        ├── RBAC -> Java SDK (only option)
        └── ABAC -> Go SDK (attribute-based policies)
```
