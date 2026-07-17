# BaSyx Setup
This setup uses BaSyx Go components and PostgreSQL.

## Start
1. Extract this archive.
2. Open a terminal in the extracted folder.
3. Start the stack:
```
docker compose up -d
```

## Endpoints
- AAS Environment: http://localhost:8082
- AAS Web UI: http://localhost:3000

## Notes
- The generated setup includes a sample RSA private key at `basyx/rsa-key.pem`.
- Infrastructure connections for the UI are defined in `basyx-infra.yml`.
- Place your own AAS files into the `aas/` folder or upload through the UI.