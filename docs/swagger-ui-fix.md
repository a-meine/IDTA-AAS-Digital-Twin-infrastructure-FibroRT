# Fixing Swagger UI for the BaSyx AAS Registry

## The Problem

When accessing the Swagger UI at `http://localhost:8083/swagger-ui/index.html`, the page loads but displays:

```
Unable to render this definition
The provided definition does not specify a valid version field.
```

This happens because the `/v3/api-docs` endpoint returns a **base64-encoded JSON string** instead of plain JSON:

```
"eyJvcGVuYXBpIjoiMy4xLjAiLCJpbmZvIjp7InRpdGxlIjoiRG90QUFTIFBhcnQgMi..."
```

Swagger UI expects a JSON object like `{"openapi": "3.1.0", ...}` and cannot parse the base64 string, so it fails to render.

## Root Cause

The BaSyx AAS Registry registers a custom `HttpMessageConverter` that overrides Spring Boot's default converters. The default `ByteArrayHttpMessageConverter` (which handles raw byte serialization) gets lost in the process. Without it, SpringDoc's `/v3/api-docs` endpoint serializes the OpenAPI spec as a base64-encoded string rather than plain JSON.

This is a known issue documented in:
- [springdoc FAQ: "Swagger UI unable to render definition"](https://springdoc.org/#why-am-i-getting-an-error-swagger-ui-unable-to-render-definition-when-overriding-the-default-spring-registered-httpmessageconverter)
- [springdoc-openapi#3181](https://github.com/springdoc/springdoc-openapi/issues/3181)
- [springdoc-openapi#2246](https://github.com/springdoc/springdoc-openapi/issues/2246)

The ideal fix is to add `ByteArrayHttpMessageConverter` back in the application code:

```java
@Override
public void configureMessageConverters(List<HttpMessageConverter<?>> converters) {
    converters.add(new ByteArrayHttpMessageConverter());
}
```

However, since we are using a pre-built Docker image (`eclipsebasyx/aas-registry-log-mongodb`), we cannot modify the Java source code directly.

## The Solution

We mount a **custom `swagger-initializer.js`** into the container that intercepts the base64 response and decodes it before passing it to Swagger UI.

### How It Works

1. Swagger UI loads `/swagger-ui/index.html`, which references `swagger-initializer.js`
2. Our custom initializer fetches `/v3/api-docs` directly
3. It detects the base64-encoded response (a JSON-encoded string)
4. It decodes it with `atob()` to get the plain OpenAPI JSON
5. It passes the decoded spec object to `SwaggerUIBundle` via the `spec` option

### Files

| File | Purpose |
|------|---------|
| `basyx/static/swagger-initializer.js` | Custom JS that decodes the base64 response |
| `docker-compose.yml` | Mounts the initializer into the container |

### Docker Volume Mount

The initializer is mounted at the Spring Boot classpath location where the original file lives inside the `swagger-ui-5.32.2.jar`:

```yaml
volumes:
  - ./basyx/static/swagger-initializer.js:/workspace/BOOT-INF/classes/META-INF/resources/webjars/swagger-ui/5.32.2/swagger-initializer.js
```

Spring Boot's classloader loads resources from `BOOT-INF/classes/` before those inside JAR files in `BOOT-INF/lib/`, so our mounted file takes precedence over the original inside the JAR.

## Setup

### 1. Images

All BaSyx components are pinned to stable milestone releases:

| Component | Image | Tag |
|-----------|-------|-----|
| AAS Environment | `eclipsebasyx/aas-environment` | `2.0.0-milestone-13` |
| AAS Registry | `eclipsebasyx/aas-registry-log-mongodb` | `2.0.0-milestone-13` |
| AAS Web UI | `eclipsebasyx/aas-gui` | `latest` |

### 2. Springdoc Configuration

The registry's `application.yml` must explicitly enable the springdoc endpoints (`basyx/aas-registry.yml`):

```yaml
springdoc:
  api-docs:
    enabled: true
    path: /v3/api-docs
  swagger-ui:
    enabled: true
    path: /swagger-ui.html
```

### 3. Start

```bash
podman compose up -d
```

### 4. Verify

Open `http://localhost:8083/swagger-ui/index.html` in your browser.

## Limitations

- The Swagger UI JS bundle itself (`swagger-ui-bundle.js`) is still the version bundled in the container image (5.32.2). Only the initializer script is overridden.
- This fix applies to the AAS Registry (`:8083`). The AAS Environment (`:8081`) Swagger UI works out of the box (same base64 behavior, but its bundled initializer apparently handles it correctly).
- The `/v3/api-docs/swagger-config` endpoint still returns the correct `url` and `configUrl`, but our custom initializer bypasses it entirely by fetching the spec directly.

## Related Links

- [Eclipse BaSyx Wiki — AAS Registry](https://wiki.basyx.org/en/latest/content/user_documentation/basyx_components/v2/aas_registry/index.html)
- [BaSyx Java Server SDK — GitHub](https://github.com/eclipse-basyx/basyx-java-server-sdk)
- [DotAAS Part 2 — Registry API Specification (SwaggerHub)](https://app.swaggerhub.com/apis/Plattform_i40/AssetAdministrationShellRegistryServiceSpecification/V3.0_SSP-001)
- [springdoc-openapi Documentation](https://springdoc.org/)
- [springdoc-openapi GitHub](https://github.com/springdoc/springdoc-openapi)
- [Swagger UI — GitHub](https://github.com/swagger-api/swagger-ui)
