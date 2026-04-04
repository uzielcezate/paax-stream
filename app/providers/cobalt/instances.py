"""
app/providers/cobalt/instances.py
Ordered list of Cobalt API instance URLs.

Priority order: index 0 is tried first.
If all instances fail, CobaltProvider raises a provider failure so
provider_manager falls back to Invidious.

Each URL is the full endpoint (POST target), not just the base.

To override via environment (optional future use):
  COBALT_INSTANCES=https://custom.instance/api/json,https://backup.instance/api/json
"""
import os
from typing import List

_DEFAULT_INSTANCES: List[str] = [
    "https://cal1.coapi.ggtyler.dev/api/json",
    "https://nyc1.coapi.ggtyler.dev/api/json",
    "https://ca.haloz.at/api/json",
]


def get_instances() -> List[str]:
    """
    Return the ordered list of Cobalt instance POST URLs.
    Reads COBALT_INSTANCES env var if set (comma-separated); falls back to defaults.
    """
    raw = os.getenv("COBALT_INSTANCES", "")
    if raw.strip():
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(_DEFAULT_INSTANCES)
