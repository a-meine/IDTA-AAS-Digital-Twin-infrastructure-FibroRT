#!/usr/bin/env python3
"""
Heartbeat service for registering local AAS shell descriptors
with the central Universal AAS registry.

Runs on each remote AAS server. Periodically fetches shell descriptors
from the local AAS registry and syncs them to the central registry.
"""

import time
import sys
import base64
import requests
from urllib.parse import urlparse
from config import (
    CENTRAL_REGISTRY_URL,
    LOCAL_REGISTRY_URL,
    MY_PUBLIC_IP,
    MY_PORT,
    MY_WEB_UI_URL,
    HEARTBEAT_INTERVAL,
    KEYCLOAK_URL,
    KEYCLOAK_CLIENT_ID,
    KEYCLOAK_CLIENT_SECRET,
    KEYCLOAK_REALM,
)


def b64url_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def unwrap_baaxyx_envelope(data):
    """Unwrap BaSyx v3 response envelope: {"paging_metadata":{},"result":[...]} -> list."""
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data if isinstance(data, list) else []


def get_jwt_token():
    """Authenticate with Keycloak using client credentials and return a JWT token."""
    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": KEYCLOAK_CLIENT_SECRET,
    }
    resp = requests.post(url, data=data, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_local_shells():
    """Fetch all shell descriptors from the local AAS registry."""
    url = f"{LOCAL_REGISTRY_URL}/shell-descriptors"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return unwrap_baaxyx_envelope(resp.json())


def transform_endpoints(shells):
    """Replace localhost/0.0.0.0 endpoints with this machine's public IP in protocolInformation.href."""
    for shell in shells:
        for ep in shell.get("endpoints", []):
            proto_info = ep.get("protocolInformation", {})
            href = proto_info.get("href", "")
            if href:
                parsed = urlparse(href)
                host = parsed.hostname or ""
                if host in ("localhost", "0.0.0.0", "127.0.0.1"):
                    proto_info["href"] = href.replace(host, MY_PUBLIC_IP)
            proto_info["endpointProtocol"] = "https"
    return shells


def get_central_shell_ids(token):
    """Fetch all shell descriptor IDs currently in the central registry."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{CENTRAL_REGISTRY_URL}/shell-descriptors"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    shells = unwrap_baaxyx_envelope(resp.json())
    return {s.get("id") for s in shells}


def sync_to_central(shells, token):
    """PUT each shell descriptor to the central registry. Remove stale entries."""
    headers = {"Authorization": f"Bearer {token}"}
    synced = 0

    # Get current central IDs to detect removals
    central_ids = get_central_shell_ids(token)
    local_ids = set()

    for shell in shells:
        shell_id = shell.get("id", "")
        if not shell_id:
            continue
        local_ids.add(shell_id)
        encoded_id = b64url_encode(shell_id)
        url = f"{CENTRAL_REGISTRY_URL}/shell-descriptors/{encoded_id}"
        resp = requests.put(url, json=shell, headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            synced += 1
        else:
            print(f"  [WARN] Failed to sync {shell_id}: {resp.status_code} {resp.text[:200]}")

    # Remove shells from central that no longer exist locally
    stale_ids = central_ids - local_ids
    for stale_id in stale_ids:
        encoded_id = b64url_encode(stale_id)
        url = f"{CENTRAL_REGISTRY_URL}/shell-descriptors/{encoded_id}"
        resp = requests.delete(url, headers=headers, timeout=10)
        if resp.status_code in (200, 204):
            print(f"  [CLEANUP] Removed stale shell: {stale_id}")

    return synced


def main():
    print("[heartbeat] Starting Universal AAS heartbeat service")
    print(f"  Local registry:   {LOCAL_REGISTRY_URL}")
    print(f"  Central registry:  {CENTRAL_REGISTRY_URL}")
    print(f"  Public IP:         {MY_PUBLIC_IP}:{MY_PORT}")
    print(f"  Web UI URL:        {MY_WEB_UI_URL}")
    print(f"  Interval:          {HEARTBEAT_INTERVAL}s")
    print(f"  Keycloak:          {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}")
    print()

    while True:
        try:
            token = get_jwt_token()
            shells = get_local_shells()
            shells = transform_endpoints(shells)
            synced = sync_to_central(shells, token)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  [{timestamp}] Synced {synced}/{len(shells)} shells to central registry")
        except requests.exceptions.ConnectionError as e:
            print(f"  [ERROR] Connection failed: {e}", file=sys.stderr)
        except requests.exceptions.Timeout:
            print("  [ERROR] Request timed out", file=sys.stderr)
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)

        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
