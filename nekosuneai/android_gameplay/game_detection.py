"""Identify the current Android game by foreground application package.

Unknown packages are never guessed to be games. Owners may register additional
package-to-title mappings without changing the generic capture/ADB runtime.
"""
from __future__ import annotations

KNOWN_GAMES = {
    "com.moonactive.cmboard": "Coin Master – Board Adventure",
    "com.moonactive.coinmaster": "Coin Master",
    "com.superplaystudios.disneysolitairedreams": "Disney Solitaire",
    "com.superplaystudios.dicedreams": "Dice Dreams",
}


def identify_game(package_id: str, allowed_packages=(), names=None) -> dict:
    package_id = str(package_id or "").strip()
    titles = dict(KNOWN_GAMES)
    if names:
        titles.update({str(k): str(v) for k, v in names.items() if k and v})
    approved = package_id in set(allowed_packages)
    known = package_id in titles
    return {
        "package_id": package_id,
        "game_id": package_id if approved else None,
        "game_name": titles.get(package_id, "Unknown app"),
        "known_game": known,
        "approved": approved,
        "playing": bool(package_id and approved),
    }


def detect_foreground(device, allowed_packages=(), names=None) -> dict:
    return identify_game(device.foreground_package(), allowed_packages, names)
