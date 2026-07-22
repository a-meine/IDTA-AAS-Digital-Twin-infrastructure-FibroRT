# Web Authentication Flow — Full Explanation

## 1. What is a JWT?

A **JWT (JSON Web Token)** is a signed JSON blob that travels between components. It proves "who you are" and "what you're allowed to do." It has three parts separated by dots:

```
eyJhbGciOiJSUzI1NiIs...    .    eyJleHAiOjE3...    .    SflKxwRJSM...
     Header (algorithm)          Payload (data)           Signature (proof)
```

The **payload** contains claims like:
```json
{
  "iss": "https://192.168.56.212:9443/realms/BaSyx",
  "sub": "ca84d53a-...",
  "preferred_username": "admin",
  "realm_access": {
    "roles": ["admin"]
  },
  "exp": 1234567890
}
```

The **signature** proves the token was issued by Keycloak and wasn't tampered with. Anyone can read the payload, but only Keycloak can produce a valid signature.

---

## 2. Who issues the JWT?

**Keycloak** — defined in two files:

### File chain for Keycloak startup:

```
.env
  KC_BOOTSTRAP_ADMIN_USERNAME=admin          ← Keycloak admin login
  KC_BOOTSTRAP_ADMIN_PASSWORD=admin
  KC_DB_USERNAME=keycloak                    ← PostgreSQL login
  KC_DB_PASSWORD=keycloak_db_pass
  HOST_IP=192.168.56.212
        │
        ▼
docker-compose.yml:90-122
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    command: start-dev --import-realm        ← starts Keycloak + imports realm
    environment:
      KC_HOSTNAME: ${HOST_IP}                ← generates URLs with this host
      KC_HOSTNAME_PORT: "9443"               ← external port (nginx:9443)
      KC_HOSTNAME_STRICT_HTTPS: "true"       ← generates https:// URLs
      KC_PROXY_HEADERS: "xforwarded"         ← trusts X-Forwarded-* from nginx
    volumes:
      - ./keycloak/realm-export.json:/opt/keycloak/data/import/realm-export.json:ro
        │                                            ▲
        │                                            │
        ▼                                            │
docker-compose.yml:75-88
  keycloak-db:                                   keycloak/realm-export.json
    image: postgres:16-alpine                        Defines:
    POSTGRES_DB: keycloak                            ├── Realm: "BaSyx"
    volumes:                                         ├── Clients: basyx-web-ui, basyx-admin
      - keycloak-db-data:/var/lib/postgresql/data    ├── Roles: admin, reader, uploader
                                                     ├── Users: admin/admin, reader/reader, uploader/uploader
                                                     └── Client Scopes: openid, profile, email, roles
```

Keycloak stores all its configuration (realm, users, roles, clients) in PostgreSQL. The `realm-export.json` is auto-imported on first start via `--import-realm`.

---

## 3. What is the OAuth2 Auth Code flow?

This is the login dance between browser, Keycloak, and the AAS Web UI. It uses **PKCE** (Proof Key for Code Exchange) for security. PKCE requires `crypto.subtle`, which only works in **HTTPS** or **localhost** — that's why nginx with TLS is mandatory.

---

## 4. The full authentication flow, step by step

### Step 1: User opens the Web UI

```
Browser → https://192.168.56.212:8443/
```

nginx (nginx.conf:30-49) routes this to the AAS Web UI SPA:

```
nginx.conf:41
  location / {
      proxy_pass http://aas-web-ui:3000;
      proxy_set_header X-Forwarded-Proto $scheme;
  }
```

### Step 2: SPA reads its config

The AAS Web UI container has `basyx-infra.yml` mounted (docker-compose.yml:51):

```yaml
# basyx-infra.yml:16-22
security:
  type: oauth2
  config:
    flow: auth_code
    issuer: "https://192.168.56.212:9443/realms/BaSyx"
    clientId: "basyx-web-ui"
```

This tells the SPA: "You must use OAuth2 login. The identity provider is at this URL. Your client ID is `basyx-web-ui`."

### Step 3: SPA discovers Keycloak endpoints

The SPA fetches Keycloak's OIDC discovery document:

```
GET https://192.168.56.212:9443/realms/BaSyx/.well-known/openid-configuration
```

nginx routes `:9443` to Keycloak (nginx.conf:56-71):

```
nginx.conf:63
  location / {
      proxy_pass http://keycloak:8080;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header X-Forwarded-Host  $host;
  }
```

Keycloak responds with a JSON listing all its endpoints:

```json
{
  "authorization_endpoint": "https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/auth",
  "token_endpoint": "https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/token",
  "jwks_uri": "https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/certs",
  "end_session_endpoint": "https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/logout"
}
```

### Step 4: SPA generates PKCE challenge

In the browser, the SPA generates:

```
code_verifier  = random43to128Chars      ← secret, kept in browser memory
code_challenge = BASE64URL(SHA256(code_verifier))  ← proof, sent to Keycloak
```

This requires `crypto.subtle` — only available in HTTPS or localhost.

### Step 5: Browser redirects to Keycloak login

```
Browser → https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/auth
  ?response_type=code
  &client_id=basyx-web-ui                          ← from basyx-infra.yml:22
  &redirect_uri=https://192.168.56.212:8443/       ← must match realm-export.json:33
  &code_challenge=EixUz7...
  &code_challenge_method=S256
  &scope=openid profile email roles
```

The `client_id` comes from basyx-infra.yml:22. The `redirect_uri` must match one of the `redirectUris` in realm-export.json:32-34.

### Step 6: User logs in at Keycloak

The user sees the Keycloak login page and enters credentials. Keycloak checks against its PostgreSQL database:

```
Keycloak → PostgreSQL (keycloak-db:5432)
  SELECT * FROM users WHERE username = 'admin'
  → finds user from realm-export.json:85-101
  → password matches (realm-export.json:94: "value": "admin")
```

### Step 7: Keycloak issues the JWT

Keycloak generates the access token with claims based on the user's role assignments and the **protocol mappers** defined in the `roles` client scope:

```
realm-export.json:284-307  (the "roles" client scope)
  protocolMapper: oidc-usermodel-realm-role-mapper
  config:
    claim.name: "realm_access.roles"    ← where roles go in the JWT
    access.token.claim: "true"          ← include in access token
    multivalued: "true"                 ← it's an array
```

So for user `admin` (who has `realmRoles: ["admin"]` from realm-export.json:99-101), Keycloak generates:

```json
{
  "iss": "https://192.168.56.212:9443/realms/BaSyx",
  "sub": "ca84d53a-...",
  "preferred_username": "admin",
  "realm_access": {
    "roles": ["admin"]
  },
  "exp": 1234567890
}
```

Other mappers add `family_name`, `given_name`, `email` (from the profile and email scopes in realm-export.json:196-281).

### Step 8: Keycloak redirects back to SPA with auth code

```
Browser → https://192.168.56.212:8443/?code=SplxlO...&state=abc123
```

### Step 9: SPA exchanges code for JWT

The SPA sends (server-side or via backend):

```
POST https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/token
  grant_type=authorization_code
  code=SplxlO...
  redirect_uri=https://192.168.56.212:8443/
  client_id=basyx-web-ui
  code_verifier=<original random string>     ← proves PKCE
```

Keycloak validates the code + verifier and returns:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "...",
  "expires_in": 300
}
```

### Step 10: SPA stores the JWT

The SPA stores the access token in memory (or localStorage/sessionStorage). Every subsequent API call includes it in the `Authorization` header.

---

## 5. How the AAS Environment validates the JWT

When the SPA makes an API call like `GET /shells`, nginx proxies it to the AAS Environment (nginx.conf:30-31):

```
nginx.conf:30
  location ~ ^/(shells|submodels|concept-descriptions) {
      proxy_pass http://aas-environment:8081;
  }
```

The request arrives at the AAS Environment with:

```
GET http://aas-environment:8081/shells
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
```

The AAS Environment's Spring Security validates the JWT using three properties from application.properties:

### Validation step 1: Check the signature

```
application.properties:32
  spring.security.oauth2.resourceserver.jwt.jwk-set-uri=http://keycloak:8080/realms/BaSyx/protocol/openid-connect/certs
```

The AAS Environment fetches Keycloak's public signing keys from this **internal Docker network URL** (container-to-container, no TLS needed). It uses these keys to verify the JWT signature wasn't forged.

### Validation step 2: Check the issuer

```
application.properties:30
  spring.security.oauth2.resourceserver.jwt.issuer-uri=https://${HOST_IP}:9443/realms/BaSyx
```

The `iss` claim in the JWT must exactly match this URL. If Keycloak generated the token with `iss: "https://192.168.56.212:9443/realms/BaSyx"`, it matches. If the `KC_HOSTNAME` or `KC_HOSTNAME_PORT` were wrong, this check would fail.

### Validation step 3: Check RBAC rules

```
application.properties:22-25
  basyx.feature.authorization.enabled=true
  basyx.feature.authorization.type=rbac
  basyx.feature.authorization.jwtBearerTokenProvider=keycloak
  basyx.feature.authorization.rbac.file=file:/config/rbac_rules.json
```

The `jwtBearerTokenProvider=keycloak` tells BaSyx how to extract roles from the JWT. Keycloak's format is `realm_access.roles` — this is a hardcoded convention in BaSyx's Keycloak provider.

The AAS Environment reads the `realm_access.roles` claim from the JWT (e.g., `["admin"]`) and checks it against `rbac_rules.json`.

---

## 6. The role-to-JWT-to-RBAC chain

Here's how the pieces connect end-to-end:

```
realm-export.json                    Keycloak                 JWT Payload              rbac_rules.json
 defining users + roles           issues tokens              contains               defines permissions
─────────────────────          ────────────────          ──────────────          ────────────────────

users:                         User logs in →            {                        role: "admin",
  admin:                          │                       "realm_access": {          action: CRUD+EXECUTE,
    realmRoles: ["admin"]         │                        "roles": ["admin"]        target: aas-environment
    realmExport.json:99-101       │                       }                       },
         │                        │                        ▲                         │
         │                        ▼                        │                         │
         │              Keycloak generates JWT ────────────┘                         │
         │              using "roles" client scope                                    │
         │              (realm-export.json:284-307)                                   │
         │                                                                           │
         │              "realm-roles" mapper puts                                    │
         │              realm_access.roles into JWT                                  │
         │              (realm-export.json:292-306)                                   │
         │                                                                           │
         │                                        AAS Environment reads JWT ──────────┘
         │                                        extracts realm_access.roles
         │                                        matches against rbac_rules.json
         │                                        application.properties:24
         │                                          jwtBearerTokenProvider=keycloak
```

---

## 7. File dependency map

```
.env ──────────────────────► docker-compose.yml ──► keycloak container
  HOST_IP                       │                       │
  KC_DB_*                       │                       ├── imports realm-export.json
  MONGO_*                       │                       │      (realm, clients, users,
                                │                       │       roles, scopes, mappers)
                                │                       │
                                ├──► aas-environment ◄──┘
                                │       │
                                │       ├── application.properties
                                │       │     ├── basyx.feature.authorization.enabled=true
                                │       │     ├── basyx.feature.authorization.type=rbac
                                │       │     ├── basyx.feature.authorization.rbac.file=file:/config/rbac_rules.json
                                │       │     ├── jwt.issuer-uri=https://HOST_IP:9443/realms/BaSyx
                                │       │     └── jwt.jwk-set-uri=http://keycloak:8080/.../certs
                                │       │
                                │       └── rbac_rules.json (mounted at /config/rbac_rules.json)
                                │
                                ├──► aas-web-ui (aas-gui)
                                │       │
                                │       ├── basyx-infra.yml (mounted)
                                │       │     ├── security.type: oauth2
                                │       │     ├── security.config.flow: auth_code
                                │       │     ├── security.config.issuer: https://HOST_IP:9443/realms/BaSyx
                                │       │     └── security.config.clientId: basyx-web-ui
                                │       │
                                │       └── Environment variables:
                                │             ALLOW_UPLOADING=true, ALLOW_EDITING=true, etc.
                                │
                                ├──► nginx
                                │       ├── nginx.conf
                                │       │     ├── :8443 → aas-web-ui:3000 (SPA)
                                │       │     ├── :8443/shells|submodels|... → aas-environment:8081
                                │       │     └── :9443 → keycloak:8080
                                │       └── certs/server.crt + server.key
                                │
                                └──► aas-registry
                                        └── aas-registry.yml
                                              ├── jwt.issuer-uri: https://HOST_IP:9443/realms/BaSyx
                                              └── jwt.jwk-set-uri: http://keycloak:8080/.../certs
```

---

## 8. The two Keycloak clients

| | `basyx-web-ui` (realm-export.json:24-47) | `basyx-admin` (realm-export.json:48-63) |
|---|---|---|
| **Used by** | AAS Web UI (browser) | Server-to-server calls, curl testing |
| **Type** | Public (no secret needed) | Confidential (needs `secret`) |
| **Flow** | Authorization Code + PKCE | Client Credentials / Direct Access |
| **`directAccessGrantsEnabled`** | `false` | `true` |
| **`serviceAccountsEnabled`** | `false` | `true` |
| **`redirectUris`** | `https://192.168.56.212:8443/*` | none |
| **Secret** | none (public) | `basyx-admin-secret-change-me` |

---

## 9. Why nginx is mandatory

Without HTTPS (plain HTTP), the browser blocks `crypto.subtle`:

```
Browser on http://192.168.56.212:8443
  → crypto.subtle is undefined
  → PKCE code_challenge generation fails
  → "Failed to initiate OAuth2 authorization flow"
```

nginx terminates TLS using the self-signed cert (`nginx/certs/server.crt`). The browser shows a warning, but once accepted, `crypto.subtle` works and the OAuth2 flow succeeds. That's why every URL in the system uses `https://` on ports `8443` and `9443`.

---

## 10. Token lifespan

From realm-export.json:20-22:

```
"accessTokenLifespan": 300         ← JWT expires after 5 minutes
"ssoSessionIdleTimeout": 1800      ← session expires after 30 min idle
"ssoSessionMaxLifespan": 36000     ← session expires after 10 hours max
```

After 5 minutes, the SPA must use the `refresh_token` to get a new `access_token` without requiring the user to log in again.
