#!/usr/bin/env python3
"""
Universal AAS Discovery UI — lightweight dashboard for browsing
all registered AAS across the distributed system.
"""

import os
import requests
from flask import Flask, render_template, jsonify
from urllib.parse import urlparse

app = Flask(__name__)
CENTRAL_REGISTRY_URL = os.getenv("CENTRAL_REGISTRY_URL", "http://central-registry:8080")


@app.route("/")
def index():
    return render_template("index.html")


def fetch_shells():
    """Fetch shell descriptors from the central registry, unwrapping the BaSyx envelope."""
    resp = requests.get(
        f"{CENTRAL_REGISTRY_URL}/shell-descriptors",
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data if isinstance(data, list) else []


@app.route("/api/shells")
def api_shells():
    """Proxy to central registry, return all shell descriptors."""
    try:
        shells = fetch_shells()
        return jsonify(shells)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/servers")
def api_servers():
    """Aggregate shells by server IP, return server summaries."""
    try:
        shells = fetch_shells()

        servers = {}
        for shell in shells:
            for ep in shell.get("endpoints", []):
                proto_info = ep.get("protocolInformation", {})
                href = proto_info.get("href", "")
                if href:
                    parsed = urlparse(href)
                    ip = parsed.hostname or "unknown"
                    port = parsed.port or 8081
                else:
                    ip = ep.get("host", "unknown")
                    port = ep.get("port", 8081)
                if ip not in servers:
                    servers[ip] = {
                        "ip": ip,
                        "port": port,
                        "protocol": proto_info.get("endpointProtocol", "https"),
                        "shell_count": 0,
                        "shells": [],
                    }
                servers[ip]["shell_count"] += 1
                servers[ip]["shells"].append(
                    shell.get("idShort", shell.get("id", ""))
                )

        return jsonify(list(servers.values()))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/health/<ip>")
def api_health(ip):
    """Check if a remote AAS server is reachable."""
    try:
        resp = requests.get(f"http://{ip}:8081/shells", timeout=5)
        return jsonify({"ip": ip, "reachable": resp.status_code == 200})
    except Exception:
        return jsonify({"ip": ip, "reachable": False})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001, debug=False)
