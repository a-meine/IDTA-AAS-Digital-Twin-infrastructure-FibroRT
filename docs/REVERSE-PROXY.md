# Reverse Proxy & HTTPS Configuration

> Solves two problems: OAuth2 PKCE requires a secure context (HTTPS), and the
> browser must reach all services from a single origin to avoid mixed-content
> and self-signed-cert-per-port issues.

---

## Problem Statement

The BaSyx AAS Web UI is a client-side SPA. After OAuth2 login, the browser
makes direct `fetch()` calls to the AAS Environment REST API. Three blockers
prevented this from working across the local network:

1. **PKCE secure context** -- OAuth2 Authorization Code flow with PKCE calls
   `crypto.subtle.digest()` to hash the code verifier. The browser only allows
   this in a **secure context** (`https://` or `http://localhost`). Plain
   `http://192.168.56.212` is neither.

2. **Mixed content** -- Even after adding HTTPS for the Web UI (`:8443`), the
   SPA's `basyx-infra.yml` pointed API calls to `http://192.168.56.212:8081`.
   Browsers block HTTPS pages from fetching HTTP resources.

3. **Self-signed cert per port** -- Routing the AAS Environment through a
   separate HTTPS port (`:8444`) requires the browser to accept a separate
   SSL certificate warning for that port. Modern browsers silently reject
   `fetch()` to untrusted-HTTPS origins (no dialog is shown for background
   requests, only navigation triggers the cert-acceptance dialog).

## Solution: Path-Based Routing on a Single Port

All browser-facing traffic goes through **one nginx port (8443)** with TLS.
API paths are proxied to the AAS Environment by path, so the browser only
ever talks to a single origin.

```
Browser (any machine)
  |
  | HTTPS :8443 (one cert to accept)
  |
  v
nginx
  |-- /shells/*, /submodels/*, /concept-descriptions/*
  |     --> proxy_pass http://aas-environment:8081
  |
  |-- /*  (everything else)
        --> proxy_pass http://aas-web-ui:3000  (static SPA)
```

### Why this works

- **Single origin** -- The browser loads the SPA and makes API calls from the
  same `https://192.168.56.212:8443` origin. No CORS, no mixed content, no
  separate cert dialogs.
- **No static-file conflicts** -- The AAS Web UI's `dist/` directory contains
  only `Logo/`, `assets/`, `config/`, `fonts/`, `index.html`, `wasm/`, and
  `worker.mjs`. None of these conflict with `/shells`, `/submodels`, or
  `/concept-descriptions`.
- **`crypto.subtle` works** -- The HTTPS page is a secure context, so PKCE
  code challenge generation succeeds.

---

## Port Map

```
Network (any machine)                  Docker Internal
================================       ==================================

:80  ──nginx──> 301 redirect to :8443
:8443 ──nginx──> /shells,/submodels,/concept-descriptions
                   ──> aas-environment:8081
                 /* ──> aas-web-ui:3000
:9443 ──nginx──> keycloak:8080
:8081 ──────────> aas-environment:8081   (direct, server-to-server / debugging)
:8083 ──────────> aas-registry:8080      (Swagger UI)
```

---

## nginx Configuration

File: `nginx/nginx.conf`

```
:80    HTTP  --> 301 redirect to https://:8443
:8443  HTTPS --> /shells,/submodels,/concept-descriptions --> aas-environment:8081
                 /* --> aas-web-ui:3000
:9443  HTTPS --> keycloak:8080
```

### Path-based routing block (inside the `:8443` server)

```nginx
location ~ ^/(shells|submodels|concept-descriptions) {
    proxy_pass http://aas-environment:8081;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Port  $server_port;
}
```

The regex matches `/shells`, `/shells/{id}`, `/submodels/{id}`, etc. and
forwards the full URI to the AAS Environment. The catch-all `location /`
below it serves the SPA.

---

## TLS Certificate

File: `nginx/certs/server.crt` + `nginx/certs/server.key`

Self-signed, 2048-bit RSA, 365 days, CN=192.168.56.212.

Critically, the certificate includes a **Subject Alternative Name (SAN)**:
```
subjectAltName=IP:192.168.56.212
```
Modern browsers ignore the CN and require a SAN. Without it, the cert is
rejected even if CN matches.

Generated with:
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/server.key \
  -out nginx/certs/server.crt \
  -addext "subjectAltName=IP:192.168.56.212" \
  -subj "/CN=192.168.56.212"
```

Users see "Not Secure" in the browser bar because the cert is self-signed.
This is expected. On each device, accept the warning once per port
(`:8443` and `:9443`).

---

## Configuration Files Changed

### `basyx-infra.yml` -- API URLs use same origin

```yaml
components:
  aasRepository:
    baseUrl: https://192.168.56.212:8443/shells
  submodelRepository:
    baseUrl: https://192.168.56.212:8443/submodels
  conceptDescriptionRepository:
    baseUrl: https://192.168.56.212:8443/concept-descriptions
security:
  type: oauth2
  config:
    flow: auth_code
    issuer: "https://192.168.56.212:9443/realms/BaSyx"
    clientId: "basyx-web-ui"
```

### `docker-compose.yml` -- nginx ports

```yaml
nginx:
  ports:
    - "80:80"        # HTTP redirect to :8443
    - "8443:8443"    # HTTPS: SPA + AAS Environment API (path-based)
    - "9443:9443"    # HTTPS: Keycloak
```

### `basyx/application.properties` -- CORS origin

```properties
basyx.cors.allowed-origins=https://${HOST_IP}:8443
```

With path-based routing, API requests come from the **same origin** as the
SPA, so CORS headers are not strictly required. They remain as a safety net
for direct `:8081` access or future cross-origin clients.

### `keycloak/realm-export.json` -- Redirect URIs

```json
"redirectUris": ["https://192.168.56.212:8443/*"],
"webOrigins": ["https://192.168.56.212:8443"]
```

---

## Keycloak Proxy Headers

Keycloak is behind nginx but must generate external URLs pointing to
`:9443`. This is configured with:

```yaml
# docker-compose.yml
KC_HOSTNAME: ${HOST_IP}           # 192.168.56.212
KC_HOSTNAME_PORT: "9443"
KC_HOSTNAME_STRICT_HTTPS: "true"
KC_PROXY_HEADERS: "xforwarded"    # Trust X-Forwarded-* from nginx
```

nginx sends `X-Forwarded-Proto: https` and `X-Forwarded-Host: 192.168.56.212`,
so Keycloak's OIDC discovery endpoint returns:
```json
"authorization_endpoint": "https://192.168.56.212:9443/realms/BaSyx/protocol/openid-connect/auth"
```

---

## JWT Validation Chain

```
Browser --> Authorization: Bearer <JWT> --> nginx:8443 --> aas-environment:8081

AAS Environment:
  1. Checks JWT issuer = https://192.168.56.212:9443/realms/BaSyx
  2. Fetches signing keys from http://keycloak:8080/.../certs (internal Docker network)
  3. Verifies signature
  4. Checks RBAC rules (rbac_rules.json)
```

- `issuer-uri` (external) must use HTTPS:9443 to match the JWT `iss` claim
- `jwk-set-uri` (internal) uses HTTP over the Docker network (no TLS needed)

---

## Startup Order

```
MongoDB ─────────────────────────────────┐
                                         ├──> aas-environment
PostgreSQL ──> Keycloak ─────────────────┤
                                         ├──> aas-registry
                                         ├──> nginx (waits for Keycloak healthy)
                                         │
                             aas-web-ui ──┘ (waits for aas-environment)
```

Healthchecks ensure nginx doesn't start until Keycloak is ready. The AAS
Web UI waits for the AAS Environment to be up before starting.

---

## Troubleshooting

### "TypeError: Failed to load" from other PCs

**Cause:** The browser hasn't accepted the self-signed cert for `:8443`.
Navigation to the URL shows the cert warning; background `fetch()` does not.

**Fix:** Open `https://192.168.56.212:8443` in the browser, click
"Advanced" > "Proceed". Then do the same for `https://192.168.56.212:9443`
(Keycloak). These accept the cert for that browser profile.

### Port 80 redirect doesn't work in browser

**Cause:** Browser cache or HSTS from a previous session.

**Fix:** Clear Safari cache/cookies, or test in Chrome incognito.

### Keycloak shows wrong OIDC URLs (http:// instead of https://)

**Cause:** `KC_PROXY_HEADERS` not set or X-Forwarded-* headers missing.

**Fix:** Verify `KC_PROXY_HEADERS: "xforwarded"` in docker-compose.yml and
that nginx sends `X-Forwarded-Proto` and `X-Forwarded-Host`.

### CORS errors in browser console

**Cause:** `allowed-origins` doesn't match the browser's origin.

**Fix:** Ensure `application.properties` has `basyx.cors.allowed-origins=https://${HOST_IP}:8443`.

### AAS Registry Swagger UI returns 401

**Cause:** Authorization is enabled on the registry.

**Fix:** Set `authorization.enabled: false` in `basyx/aas-registry.yml`.

---

## Restart Command

```bash
cd /Users/Aziz/Downloads/basyx-setup
/opt/podman/bin/podman compose down && /opt/podman/bin/podman compose up -d
```

Note: Using `podman compose` with the external `docker-compose` provider,
NOT `docker compose` (Docker Desktop has a bad CPU type on this machine).
