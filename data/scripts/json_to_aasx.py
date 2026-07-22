#!/usr/bin/env python3
"""Convert a DPP JSON file to AASX using basyx.aas.adapter.

Usage:
    python json_to_aasx.py DPP_filled.json DPP_FIBROTOR_ER15_V2.aasx \
        --aas-id "https://example.com/aas/FIBROTOR_ER15" \
        --aas-id-short "DPP_FIBROTOR_ER15_V2" \
        --submodel-prefix "https://example.com/submodel/FIBROTOR_ER15"

Without --aas-id, the IDs from the JSON are used as-is (legacy behavior).
"""

import argparse
import json
import os
import sys

from basyx.aas.adapter.json.json_deserialization import read_aas_json_file
from basyx.aas.adapter.aasx import AASXWriter, DictSupplementaryFileContainer

PART_NAME = "/aasx/aas.xml"

# Default submodel ID suffixes (relative to submodel-prefix)
SUBMODEL_SUFFIXES = {
    "TechnicalData": "TechnicalData/2/0",
    "Nameplate": "DigitalNameplate/3/0",
    "CarbonFootprint": "CarbonFootprint/1/0",
    "HandoverDocumentation": "HandoverDocumentation/2/0",
    "MaintenanceInstructions": "MaintenanceInstructions/1/0",
}


def patch_object_store(object_store, aas_id, aas_id_short, submodel_prefix):
    """Patch AAS and submodel IDs in the object store for uniqueness."""
    from basyx.aas import model

    # Build mapping of old submodel IDs -> new submodel IDs
    sm_id_map: dict = {}

    for obj in object_store:
        if isinstance(obj, model.AssetAdministrationShell):
            old_id = obj.id
            obj.id = aas_id
            print(f"  Patched AAS: {old_id} -> {aas_id}")
            if aas_id_short:
                old_short = obj.id_short
                obj.id_short = aas_id_short
                print(f"  Patched AAS idShort: {old_short} -> {aas_id_short}")
            # Patch globalAssetId
            if obj.asset_information:
                obj.asset_information.global_asset_id = aas_id.replace("/aas/", "/asset/")
            # Build new submodel references (old keys are immutable)
            new_refs = set()
            for ref in obj.submodel:
                old_val = ref.key[0].value
                new_val = None
                for name, suffix in SUBMODEL_SUFFIXES.items():
                    if name.lower() in old_val.lower() or name in old_val:
                        new_val = f"{submodel_prefix}/{suffix}"
                        sm_id_map[old_val] = new_val
                        break
                if new_val:
                    new_key = model.Key(model.KeyTypes.SUBMODEL, new_val)
                    new_refs.add(model.ModelReference((new_key,), model.Submodel))
                    print(f"  Patched submodel ref: {old_val} -> {new_val}")
                else:
                    new_refs.add(ref)
            obj.submodel = new_refs

        elif isinstance(obj, model.Submodel):
            old_id = obj.id
            for name, suffix in SUBMODEL_SUFFIXES.items():
                if name.lower() in old_id.lower() or name in old_id:
                    new_id = f"{submodel_prefix}/{suffix}"
                    obj.id = new_id
                    print(f"  Patched submodel: {old_id} -> {new_id}")
                    break


def main():
    parser = argparse.ArgumentParser(description="Convert DPP JSON to AASX")
    parser.add_argument("json_path", help="Input JSON file")
    parser.add_argument("aasx_path", help="Output AASX file")
    parser.add_argument("--aas-id", help="Unique AAS ID for this product")
    parser.add_argument("--aas-id-short", help="Unique AAS idShort")
    parser.add_argument("--submodel-prefix", help="Prefix for submodel IDs")
    args = parser.parse_args()

    print(f"Reading {args.json_path}...")
    object_store = read_aas_json_file(args.json_path)
    print(f"  Loaded {len(object_store)} objects")

    if args.aas_id:
        submodel_prefix = args.submodel_prefix or args.aas_id.replace("/aas/", "/submodel/")
        patch_object_store(object_store, args.aas_id, args.aas_id_short, submodel_prefix)

    for obj in object_store:
        print(f"  - {type(obj).__name__}: {getattr(obj, 'id_short', '?')}")

    print(f"\nWriting {args.aasx_path}...")
    file_store = DictSupplementaryFileContainer()
    with open(args.aasx_path, "wb") as f:
        writer = AASXWriter(f)
        writer.write_all_aas_objects(PART_NAME, object_store, file_store)
        writer.close()

    size = os.path.getsize(args.aasx_path)
    print(f"Done! {args.aasx_path} ({size:,} bytes)")


if __name__ == "__main__":
    main()
