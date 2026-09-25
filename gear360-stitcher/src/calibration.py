"""Calibration profile loading/saving for the Gear 360 (SM-R210) dual-fisheye lenses.

Calibration values are stored as fractions relative to each lens's square region
size (not absolute pixels), so a single profile works for both photo resolution
(5792x2896, lens square 2896) and video resolution (2560x1280, lens square 1280).
"""
import json
import os

DEFAULT_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "calibration_profiles",
    "default.json",
)

DEFAULT_CALIBRATION = {
    "front": {"cx_frac": 0.5, "cy_frac": 0.5, "radius_frac": 0.5, "fov_deg": 195.0},
    "back": {
        "cx_frac": 0.5,
        "cy_frac": 0.5,
        "radius_frac": 0.5,
        "fov_deg": 195.0,
        "rotation_deg": 0.0,
    },
    "feather_frac": 0.85,
}


def load_calibration(path=None):
    path = path or DEFAULT_PROFILE_PATH
    if not os.path.isfile(path):
        return json.loads(json.dumps(DEFAULT_CALIBRATION))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = json.loads(json.dumps(DEFAULT_CALIBRATION))
    merged["front"].update(data.get("front", {}))
    merged["back"].update(data.get("back", {}))
    merged["feather_frac"] = data.get("feather_frac", merged["feather_frac"])
    return merged


def save_calibration(calibration, path=None):
    path = path or DEFAULT_PROFILE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2)
