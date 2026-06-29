"""
Drop-in helper — copy this function into each bot script.
Each bot calls apply_custom_universe(base_list, "hm") at startup.
custom_universe.json lives in C:\\Trade\\dashboard\\
"""
from __future__ import annotations
import json
import os


CUSTOM_UNIVERSE_PATH = r"C:\Trade\dashboard\custom_universe.json"


def apply_custom_universe(base_list: list[str], bot_key: str) -> list[str]:
    """Merge custom_universe.json additions/removals into the bot's base universe."""
    if not os.path.exists(CUSTOM_UNIVERSE_PATH):
        return base_list
    try:
        with open(CUSTOM_UNIVERSE_PATH) as f:
            cfg = json.load(f)
        section = cfg.get(bot_key, {})
        add    = set(section.get("add", []) + section.get("extra", []))
        remove = set(section.get("remove", []))
        result = [s for s in base_list if s not in remove]
        for s in add:
            if s not in result:
                result.append(s)
        return result
    except Exception:
        return base_list
