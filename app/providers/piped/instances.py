"""
app/providers/piped/instances.py
Ordered list of Piped API instance base URLs.

Priority order: index 0 is tried first.
If all instances fail, PipedProvider raises a provider failure so
provider_manager can fall back to Invidious.

To override via environment (future):
  PIPED_INSTANCES=https://custom.instance.xyz,https://backup.instance.com
"""
import os
from typing import List

# Default instance priority list (Phase 2)
_DEFAULT_INSTANCES: List[str] = [
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.moomoo.me",
    "https://pipedapi.syncpundit.io",
]


def get_instances() -> List[str]:
    """
    Return the ordered list of Piped instance base URLs.
    Reads PIPED_INSTANCES env var if set (comma-separated); falls back to defaults.
    """
    raw = os.getenv("PIPED_INSTANCES", "")
    if raw.strip():
        return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
    return [u.rstrip("/") for u in _DEFAULT_INSTANCES]
