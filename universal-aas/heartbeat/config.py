import os

# Central registry connection
CENTRAL_REGISTRY_URL = os.getenv("CENTRAL_REGISTRY_URL", "http://192.168.56.212:8085")

# Local AAS registry connection
LOCAL_REGISTRY_URL = os.getenv("LOCAL_REGISTRY_URL", "http://localhost:8083")

# This machine's public IP and AAS Environment port
MY_PUBLIC_IP = os.getenv("MY_PUBLIC_IP", "192.168.56.213")
MY_PORT = int(os.getenv("MY_PORT", "8081"))
MY_WEB_UI_URL = os.getenv("MY_WEB_UI_URL", f"https://{MY_PUBLIC_IP}:8443")

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))

# Keycloak configuration for JWT authentication
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://192.168.56.212:9443")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "heartbeat-registry")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "BaSyx")
