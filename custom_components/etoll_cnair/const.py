"""Constante pentru integrarea CNAIR eToll."""

DOMAIN = "etoll_cnair"

TOKEN_URL = "https://sso.etoll.ro/auth/realms/external/protocol/openid-connect/token"
API_BASE = "https://portal.etoll.ro/api"
URL_TOLLS = f"{API_BASE}/tolls"
URL_VEHICLES = f"{API_BASE}/vehicles"
URL_NOTIFICATIONS = f"{API_BASE}/notifications/summary"
URL_INVOICES = f"{API_BASE}/invoices"
CLIENT_ID = "ddcm-authz-client"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60  # minute
MIN_SCAN_INTERVAL = 15

# Statusuri care nu înseamnă o rovinietă valabilă (comparate cu majuscule)
INVALID_STATUSES = {"DRAFT", "CANCELLED", "CANCELED", "REFUNDED", "FAILED", "REJECTED"}
