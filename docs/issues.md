# Known Issues

## 1. Only One AAS Shell Uploadable — Second Upload Overwrites First

**Symptom:** Uploading two AASX files (`DPP_filled.aasx` and `DPP_FIBROTOR_ER15_V2.aasx`) results in only one shell appearing in the AAS Environment. The second upload overwrites the first.

**Root cause:** Both AASX files share the **identical AAS ID**:

```
https://admin-shell.io/idta/aas/TechnicalData/2/0
```

BaSyx identifies AAS shells by their `id` field. When you upload a second shell with the same `id`, it replaces the first one (PUT semantics, not POST).

Both files also share identical submodel IDs:
- `https://admin-shell.io/idta/SubmodelTemplate/TechnicalData/2/0`
- `https://admin-shell.io/idta/SubmodelTemplate/DigitalNameplate/3/0`
- `https://admin-shell.io/idta/SubmodelTemplate/CarbonFootprint/1/0`
- `https://admin-shell.io/idta/SubmodelTemplate/HandoverDocumentation/2/0`
- `https://admin-shell.io/idta/SubmodelTemplate/MaintenanceInstructions/1/0`

These are **template IDs** from the IDTA DPP specification, not product-specific instance IDs.

**The skeleton** (`DPP.json`) defines the AAS ID as `https://admin-shell.io/idta/aas/TechnicalData/2/0`. The `fill_dpp.py` script fills submodel data but does not modify the AAS ID. The `json_to_aasx.py` script converts JSON to AASX without changing IDs. Both products inherit the same template ID.

**Fix:** The `json_to_aasx.py` script now accepts `--aas-id` and `--submodel-prefix` arguments to generate unique IDs per product:

```bash
# Product 1
python json_to_aasx.py DPP_filled.json DPP_filled.aasx \
    --aas-id "https://example.com/aas/DPP_filled" \
    --aas-id-short "DPP_Filled"

# Product 2
python json_to_aasx.py DPP_filled.json DPP_FIBROTOR_ER15_V2.aasx \
    --aas-id "https://example.com/aas/DPP_FIBROTOR_ER15_V2" \
    --aas-id-short "DPP_FIBROTOR_ER15_V2"
```

**Note:** The submodel IDs should also be unique per product if you want to store different submodel data per product. The `--submodel-prefix` argument handles this automatically.

**Status:** Fixed in `data/scripts/json_to_aasx.py`. AASX files need to be regenerated with unique IDs.

---

## 2. Dead RBAC Rule — `viewer-uploader` Role

**Symptom:** The `viewer-uploader` role in `rbac_rules.json` has no matching Keycloak user. It grants `READ` and `CREATE` on `aas` type, but no user in `realm-export.json` has this role assigned.

**Impact:** The rule exists but is unreachable. No security risk — it's just unused code.

**Fix:** Either remove the rule or add a user with the `viewer-uploader` role in `realm-export.json`.

---

## 3. MongoDB Has No Named Volume

**Symptom:** Running `docker compose down -v` removes the MongoDB data volume. All uploaded AAS shells are lost.

**Root cause:** The `mongo` service in `docker-compose.yml` uses an anonymous Docker volume (auto-created), not a named volume.

**Fix for production:** Add a named volume:

```yaml
services:
  mongo:
    volumes:
      - mongo-data:/data/db

volumes:
  mongo-data:
```

**Status:** Not yet applied. Acceptable for development; mandatory for production.
