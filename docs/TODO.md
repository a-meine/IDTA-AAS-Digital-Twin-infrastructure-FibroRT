# Universal AAS — System TODO

> **Last scan:** 2026-07-21 19:50 UTC
> **Purpose:** Single source of truth for the current state, security issues, missing features, and incomplete tasks.
> **For other AI agents:** Read this file first to understand the full system before making changes.

---

## 0. System Context (For Other AI Agents)

### What this project is

A distributed **Asset Administration Shell (AAS)** system based on Eclipse BaSyx.
Multiple machines in a LAN each run their own AAS server stack. A central "Universal AAS" registry aggregates metadata (shell descriptors) from all servers so users can discover all products from a single dashboard.

### Architecture overview

```
Machine A (192.168.56.212) — Primary
├── Main Stack (docker-compose.yml)
│   ├── nginx (HTTPS reverse proxy :8443, :9443)
│   ├── aas-environment (:8081) — AAS data storage
│   ├── aas-registry (:8083) — local shell descriptors
│   ├── aas-web-ui (:3000 internal) — BaSyx GUI
│   ├── keycloak (:9443 via nginx) — shared auth
│   └── mongo — shared database
│
├── Universal Stack (universal-aas/docker-compose.yml)
│   ├── central-registry (:8085) — aggregates ALL shells
│   └── discovery-ui (:3001 internal) — dashboard at /universal/
│
├── Heartbeat (not running as container)
│   └── universal-aas/heartbeat/ — syncs local shells → central every 30s
│
Machine B (192.168.56.213) — Team B (separate compose)
├── nginx (:8444)
├── aas-environment (:8082)
├── aas-registry (:8084)
└── aas-web-ui

Kafka (basyx-setup-kafka-1) — DOWN, not configured
```

### Key files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Main stack: mongo, aas-env, aas-reg, keycloak, nginx |
| `universal-aas/docker-compose.yml` | Central registry + discovery UI |
| `universal-aas/heartbeat/heartbeat.py` | Auto-sync local shells → central registry |
| `universal-aas/heartbeat/config.py` | Heartbeat configuration (URLs, intervals) |
| `universal-aas/central-registry.yml` | Spring Boot config for central registry |
| `basyx/application.properties` | AAS Environment config (auth, MongoDB, Keycloak) |
| `basyx/aas-registry.yml` | Local AAS Registry config |
| `nginx/nginx.conf` | HTTPS reverse proxy (8443, 9443) |
| `keycloak/realm-export.json` | Keycloak realm (clients, roles, users) |
| `.env` | Secrets (MongoDB creds, Keycloak admin, HOST_IP) |
| `basyx/rbac_rules.json` | RBAC rules for AAS Environment |
| `basyx/rbac_rules_registry.json` | RBAC rules for local registry |
| `universal-aas/rbac_rules_central.json` | RBAC rules for central registry |
| `basyx-infra.yml` | AAS GUI infrastructure config (OAuth2 flow) |

### Networks

| Network | Containers | Purpose |
|---------|------------|---------|
| `basyx-setup_default` | mongo, keycloak, keycloak-db, aas-env, aas-reg, nginx, aas-web-ui, central-registry, discovery-ui | Main stack |
| `basyx-setup_basyx-shared` | mongo, keycloak, keycloak-db, central-registry, discovery-ui | Shared DB access for central registry |
| `team-b_team-b-internal` | Team B containers | Team B isolation |

### Running containers (as of scan time)

| Container | Image | Status | Port |
|-----------|-------|--------|------|
| nginx | nginx:alpine | Running (3h) | 80, 8443, 9443 |
| aas-environment | basyx aas-env:2.0.0-m13 | Running (14m, restarted) | 8081 |
| aas-registry | basyx aas-reg:2.0.0-m13 | Running (4h) | 8083 |
| aas-web-ui | basyx aas-gui:latest | Running (4h) | — |
| central-registry | basyx aas-reg:2.0.0-m13 | Running (4h) | 8085 |
| discovery-ui | universal-aas-discovery-ui | Running (3h) | — |
| mongo | mongo:7 | Running (4h, healthy) | 27017 |
| keycloak | keycloak:latest | Running (4h, healthy) | — |
| keycloak-db | postgres:16-alpine | Running (4h, healthy) | 5432 |
| basyx-setup-kafka-1 | cp-kafka:latest | **EXITED (1)** — BROKEN | 9092 |
| nginx-B | nginx:alpine | Running (5h) | 81, 8444 |
| aas-environment-B | basyx aas-env:2.0.0-m13 | Running (14m) | 8082 |
| aas-registry-B | basyx aas-reg:2.0.0-m13 | Running (5h) | 8084 |
| aas-web-ui-B | basyx aas-gui:latest | Running (5h) | — |
| mongo-B | mongo:7 | Running (5h, healthy) | 27017 |

---

## 1. Security Issues

### 1.1 CRITICAL — Authorization disabled on both registries

**Both** the local AAS Registry and the Central Registry have authorization **disabled**:

- `basyx/aas-registry.yml` line: `enabled: false`
- `universal-aas/central-registry.yml` line: `enabled: false`

Anyone on the network can read, create, update, or delete shell descriptors without authentication.

**Fix:** Enable authorization on both registries. The RBAC rules files already exist.

### 1.2 CRITICAL — Weak/default credentials in `.env`

```
KC_BOOTSTRAP_ADMIN_PASSWORD=12345          # trivially guessable
MONGO_PASSWORD=mongoPassword               # default weak password
KC_DB_PASSWORD=keycloak_db_pass            # predictable
KEYCLOAK_CLIENT_SECRET=heartbeat-secret-change-me  # hardcoded in config.py
```

`.env` is gitignored, but these passwords are still weak for a LAN-exposed system.

**Fix:** Generate strong random passwords. Use a secrets manager or at minimum document the rotation process.

### 1.3 HIGH — Heartbeat client secret is hardcoded

`universal-aas/heartbeat/config.py` has `heartbeat-secret-change-me` as the default Keycloak client secret. This is both a default and a weak secret.

**Fix:** Generate a real secret in Keycloak, store it in `.env`, pass as environment variable.

### 1.4 HIGH — Self-signed TLS certificate

`nginx/certs/server.crt` is self-signed (CN=192.168.56.212), expires 2027-07-20. Self-signed certs cause browser warnings and are not suitable for production.

**Fix:** Use a proper CA (internal CA, Let's Encrypt for LAN via DNS challenge, or mTLS with client certificates).

### 1.5 HIGH — No security headers in nginx

nginx config has no security headers:
- No `X-Content-Type-Options: nosniff`
- No `X-Frame-Options: DENY`
- No `Content-Security-Policy`
- No `Strict-Transport-Security` (HSTS)

**Fix:** Add security headers to nginx config.

### 1.6 MEDIUM — Swagger UI enabled in production

Both registries have `springdoc.swagger-ui.enabled: true`. This exposes API documentation publicly, leaking internal API structure.

**Fix:** Disable in production or restrict to admin-only.

### 1.7 MEDIUM — No rate limiting

nginx has no rate limiting on any endpoint. Vulnerable to brute force and DoS.

**Fix:** Add `limit_req_zone` and `limit_conn_zone` to nginx.

### 1.8 MEDIUM — No mTLS between services

Internal Docker network traffic (container-to-container) is unencrypted HTTP. Any container on the same network can intercept traffic.

**Fix:** For production, implement mTLS with a service mesh (Istio, Linkerd) or at minimum encrypt the Docker network.

### 1.9 LOW — CORS allows all headers

`basyx.cors.allowed-headers=*` in `application.properties`. This is overly permissive.

**Fix:** Restrict to specific headers needed by the application.

---

## 2. Missing / Mandatory Features

### 2.1 CRITICAL — Kafka is DOWN and not configured

The `basyx-setup-kafka-1` container exited with error:
```
Error: environment variable "KAFKA_PROCESS_ROLES" is not set
```

Kafka was intended for event-driven architecture (AAS change events, audit log streaming). It is completely non-functional.

**Fix:** Create a proper `kafka/docker-compose.yml` with KRaft mode config (no Zookeeper) or fix the existing Confluent setup.

### 2.2 CRITICAL — Heartbeat not running as a container

The heartbeat service exists as Python scripts but is NOT deployed as a Docker container. There's no `depends_on` or compose service for it. Manual deployment on remote machines is required.

**Fix:** Add heartbeat as a service in `universal-aas/docker-compose.yml` (for local machine) and create deployment instructions for remote machines.

### 2.3 HIGH — No monitoring or alerting

No monitoring stack exists:
- No Prometheus for metrics collection
- No Grafana for dashboards
- No alerting for container failures
- No health check visibility beyond `podman ps`

**Fix:** Add Prometheus + Grafana, expose BaSyx actuator endpoints (`/actuator/health`, `/actuator/metrics`).

### 2.4 HIGH — No logging aggregation

Logs are only accessible via `podman logs`. No centralized logging:
- No ELK stack (Elasticsearch, Logstash, Kibana)
- No Loki + Grafana
- No log rotation configured

**Fix:** Add structured logging and a log aggregation pipeline.

### 2.5 HIGH — No backup strategy

MongoDB data volumes exist (`basyx-setup_mongo-data`, `basyx-setup_keycloak-db-data`) but:
- No automated backups
- No backup rotation
- No restore procedure documented
- `docker compose down -v` destroys all data

**Fix:** Implement automated MongoDB dumps, backup to external storage, document restore procedure.

### 2.6 HIGH — No resource limits on containers

No container has CPU or memory limits set. A runaway container can consume all host resources.

**Fix:** Add `deploy.resources.limits` to all services in docker-compose files.

### 2.7 MEDIUM — No audit logging

No audit trail for:
- Who uploaded which AAS
- Who modified shell descriptors
- Who accessed which data
- Authentication events

**Fix:** Implement audit log via Kafka (when working) or a middleware filter.

### 2.8 MEDIUM — No API versioning

All APIs use unversioned paths (`/shells`, `/submodels`). Breaking changes will affect all clients.

**Fix:** Add API version prefix (`/v1/shells`) or use content negotiation.

### 2.9 MEDIUM — No health check endpoints exposed

BaSyx containers have actuator endpoints but they're not exposed to the host. No external health monitoring is possible.

**Fix:** Expose `/actuator/health` through nginx or a separate monitoring port.

### 2.10 LOW — No container image pinning

Most images use `latest` tag or unpinned versions:
- `eclipsebasyx/aas-gui:latest`
- `quay.io/keycloak/keycloak:latest`
- `confluentinc/cp-kafka:latest`

**Fix:** Pin to specific versions/digests for reproducibility.

---

## 3. Incomplete Tasks

### 3.1 aas-environment keeps restarting

`aas-environment` has been up only 14 minutes while other containers have been up 4+ hours. It appears to restart periodically.

**Investigate:** Check `podman logs aas-environment` for crash reasons.

### 3.2 nginx 502 for /shells after aas-environment restart

When `aas-environment` restarts, it gets a new IP on the Docker network. nginx caches the old DNS entry and returns 502 until the DNS cache expires (30s).

**Evidence from logs:**
```
connect() failed (113: Host is unreachable) while connecting to upstream,
upstream: "http://10.89.0.32:8081/shells"  ← old IP
```

**Fix:** This is a known nginx + Podman DNS issue. The `resolver 10.89.0.1` directive helps but the 30s TTL causes brief outages. Consider using a Docker network alias or health-check-based routing.

### 3.3 AASX files need regeneration with unique IDs

Both `DPP_filled.aasx` and `DPP_FIBROTOR_ER15_V2.aasx` share the same AAS ID (`https://admin-shell.io/idta/aas/TechnicalData/2/0`). Uploading the second overwrites the first.

**Fix:** Regenerate with unique IDs using `data/scripts/json_to_aasx.py --aas-id <unique-id>`.

### 3.4 Dead RBAC rule: `viewer-uploader`

`basyx/rbac_rules.json` has a `viewer-uploader` role but no Keycloak user has this role. Unused code.

**Fix:** Remove the rule or create a user with this role.

### 3.5 Discovery UI health check is hardcoded

`discovery-ui/app.py` line 84: `api_health` pings `http://{ip}:8081/shells`. This assumes all servers use port 8081, which is wrong for Team B (port 8082).

**Fix:** Read the port from the shell descriptor's `protocolInformation.href` instead.

### 3.6 No end-to-end test suite

No automated tests exist. All testing is manual via curl commands in `docs/universal-aas-testing.md`.

**Fix:** Create a test script that:
1. Starts all stacks
2. Uploads test AASX files
3. Verifies registration in local and central registries
4. Checks discovery dashboard API
5. Tests heartbeat sync
6. Validates cleanup on deletion

---

## 4. Planned Features (Not Started)

### 4.1 Event-driven architecture (Kafka)

When Kafka is working, implement:
- AAS change events (create/update/delete) published to Kafka topics
- Discovery UI subscribes for real-time updates (WebSocket)
- Audit log consumer
- Cross-server AAS change notifications

### 4.2 Submodel proxy in Discovery UI

Allow browsing submodel data directly from the discovery dashboard without navigating to the remote server. Read-only proxy that fetches submodels from the hosting server.

### 4.3 Server health monitoring

Background task in Discovery UI that pings each server and shows online/offline status. Currently the `/api/health/<ip>` endpoint exists but isn't displayed in the UI.

### 4.4 Multi-LAN support

Extend heartbeat to work across network segments with VPN/tunnel configuration.

### 4.5 AAS versioning

Support multiple versions of the same AAS. Currently each AAS ID is unique; no version history.

---

## 5. Quick Reference — Ports and URLs

| Port | Service | Access |
|------|---------|--------|
| 80 | nginx HTTP redirect | → 8443 |
| 8081 | AAS Environment (Machine A) | Direct / via nginx :8443/shells |
| 8082 | AAS Environment (Machine B) | Direct |
| 8083 | AAS Registry (Machine A) | Direct / via nginx :8443/registry/ |
| 8084 | AAS Registry (Machine B) | Direct |
| 8085 | Central Registry | Direct |
| 8443 | nginx HTTPS (Machine A) | Dashboard, API, AAS GUI |
| 8444 | nginx HTTPS (Machine B) | Team B AAS GUI |
| 9443 | nginx HTTPS → Keycloak | Auth server |

| URL | Purpose |
|-----|---------|
| `https://192.168.56.212:8443` | AAS Web UI (Machine A) |
| `https://192.168.56.212:8443/universal/` | Discovery Dashboard |
| `https://192.168.56.212:8443/universal/api/shells` | All shell descriptors |
| `https://192.168.56.212:8443/universal/api/servers` | Server aggregation |
| `https://192.168.56.212:9443` | Keycloak admin |
| `http://192.168.56.212:8085/shell-descriptors` | Central registry direct |

---

## 6. Credentials Reference (DO NOT COMMIT)

| Credential | Value | Location |
|------------|-------|----------|
| Keycloak admin | admin / 12345 | `.env` |
| MongoDB | mongoAdmin / mongoPassword | `.env` |
| Keycloak DB | keycloak / keycloak_db_pass | `.env` |
| Heartbeat client secret | heartbeat-secret-change-me | `heartbeat/config.py` |

> **Action required:** Rotate all credentials before any production deployment.
