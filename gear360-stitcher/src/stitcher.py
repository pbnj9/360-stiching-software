"""Dual-fisheye -> equirectangular stitching core.

The Gear 360 (SM-R210) captures a single frame containing two circular fisheye
images side by side: the left half from the front lens, the right half from the
back lens. Each lens covers roughly 195 degrees (equidistant/f-theta projection).
This module builds pixel-remap lookup tables (computed once per resolution and
calibration) and blends the two lenses into a standard 2:1 equirectangular frame.
"""
import numpy as np
import cv2


def _lens_map(x, y, z, lens, size, feather_frac, offset_x=0.0):
    """Compute source-pixel coordinates and blend weight for one lens.

    x, y, z: unit direction vectors expressed in the lens's own optical frame,
    where z is the forward (optical axis) component.
    """
    theta = np.arccos(np.clip(z, -1.0, 1.0))
    fov_rad = np.radians(lens["fov_deg"])
    theta_max = fov_rad / 2.0
    r_norm = theta / theta_max

    phi = np.arctan2(y, x)
    rotation = np.radians(lens.get("rotation_deg", 0.0))
    if rotation:
        phi = phi + rotation

    radius = lens["radius_frac"] * size
    cx = lens["cx_frac"] * size
    cy = lens["cy_frac"] * size

    px = cx + r_norm * radius * np.cos(phi) + offset_x
    py = cy - r_norm * radius * np.sin(phi)

    valid = r_norm <= 1.0
    weight = np.ones_like(r_norm)
    fade = r_norm > feather_frac
    weight = np.where(
        fade, np.clip((1.0 - r_norm) / (1.0 - feather_frac), 0.0, 1.0), weight
    )
    weight = np.where(valid, weight, 0.0)

    return px.astype(np.float32), py.astype(np.float32), weight.astype(np.float32)


def build_equirect_maps(src_w, src_h, out_w, out_h, calibration):
    """Precompute remap tables + blend weights for a given source/output size.

    src_w, src_h: dimensions of the raw dual-fisheye frame (e.g. 2560x1280).
    out_w, out_h: dimensions of the desired equirectangular output.
    """
    size = src_h  # each lens occupies a size x size square
    half_w = src_w / 2.0

    us = np.arange(out_w, dtype=np.float64)
    vs = np.arange(out_h, dtype=np.float64)
    uu, vv = np.meshgrid(us, vs)

    lon = (uu / out_w - 0.5) * 2.0 * np.pi  # -pi..pi, 0 = straight ahead
    lat = (0.5 - vv / out_h) * np.pi  # +pi/2 top .. -pi/2 bottom

    x = np.cos(lat) * np.sin(lon)
    y = np.sin(lat)
    z = np.cos(lat) * np.cos(lon)

    feather_frac = calibration.get("feather_frac", 0.85)

    map_x_front, map_y_front, w_front = _lens_map(
        x, y, z, calibration["front"], size, feather_frac, offset_x=0.0
    )
    # Back lens optical axis points toward -z; its local frame mirrors x and z.
    map_x_back, map_y_back, w_back = _lens_map(
        -x, y, -z, calibration["back"], size, feather_frac, offset_x=half_w
    )

    return {
        "map_x_front": map_x_front,
        "map_y_front": map_y_front,
        "w_front": w_front,
        "map_x_back": map_x_back,
        "map_y_back": map_y_back,
        "w_back": w_back,
    }


def apply_stitch(frame, maps):
    """Apply precomputed maps to a raw dual-fisheye frame, returning an
    equirectangular BGR frame (uint8)."""
    remapped_front = cv2.remap(
        frame,
        maps["map_x_front"],
        maps["map_y_front"],
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    remapped_back = cv2.remap(
        frame,
        maps["map_x_back"],
        maps["map_y_back"],
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    w_front = maps["w_front"][..., None]
    w_back = maps["w_back"][..., None]
    total = w_front + w_back
    total_safe = np.where(total > 1e-6, total, 1.0)

    blended = (
        remapped_front.astype(np.float32) * w_front
        + remapped_back.astype(np.float32) * w_back
    ) / total_safe
    blended = np.where(total > 1e-6, blended, 0.0)

    return np.clip(blended, 0, 255).astype(np.uint8)


def reframe_equirect(
    frame, yaw_deg=0.0, pitch_deg=0.0, fov_deg=90.0, out_w=1280, out_h=None
):
    """Render a perspective-corrected view from an equirectangular BGR frame.

    Positive yaw looks right; positive pitch looks upward. The output uses a
    16:9 aspect ratio by default and is suitable for viewing or exporting as a
    normal photograph.
    """
    if not 1.0 < fov_deg < 179.0:
        raise ValueError("Field of view must be between 1 and 179 degrees.")
    if out_w <= 0:
        raise ValueError("Output width must be positive.")

    src_h, src_w = frame.shape[:2]
    out_h = out_h or round(out_w * 9 / 16)
    if out_h <= 0:
        raise ValueError("Output height must be positive.")

    hfov = np.radians(fov_deg)
    vfov = 2.0 * np.arctan(np.tan(hfov / 2.0) * out_h / out_w)
    xs = np.linspace(-np.tan(hfov / 2.0), np.tan(hfov / 2.0), out_w)
    ys = np.linspace(np.tan(vfov / 2.0), -np.tan(vfov / 2.0), out_h)
    x, y = np.meshgrid(xs, ys)
    z = np.ones_like(x)
    length = np.sqrt(x * x + y * y + z * z)
    x, y, z = x / length, y / length, z / length

    pitch = np.radians(pitch_deg)
    y, z = np.cos(pitch) * y + np.sin(pitch) * z, -np.sin(pitch) * y + np.cos(pitch) * z
    yaw = np.radians(yaw_deg)
    x, z = np.cos(yaw) * x + np.sin(yaw) * z, -np.sin(yaw) * x + np.cos(yaw) * z

    longitude = np.arctan2(x, z)
    latitude = np.arcsin(np.clip(y, -1.0, 1.0))
    map_x = ((longitude / (2.0 * np.pi) + 0.5) * src_w).astype(np.float32)
    map_y = ((0.5 - latitude / np.pi) * src_h).astype(np.float32)
    return cv2.remap(
        frame,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_WRAP,
    )


def stitch_frame(frame, calibration, out_w=None, out_h=None, maps_cache=None):
    """Convenience wrapper: builds maps (or reuses maps_cache) and stitches one frame.

    maps_cache: optional dict that will be populated/reused across repeated calls
    with the same source size, output size, and calibration (e.g. video frames).
    """
    src_h, src_w = frame.shape[:2]
    out_w = out_w or src_w
    out_h = out_h or src_h

    calib_key = (
        tuple(sorted(calibration["front"].items())),
        tuple(sorted(calibration["back"].items())),
        calibration.get("feather_frac", 0.85),
    )
    cache_key = (src_w, src_h, out_w, out_h, calib_key)
    if maps_cache is not None and maps_cache.get("_key") == cache_key:
        maps = maps_cache["_maps"]
    else:
        maps = build_equirect_maps(src_w, src_h, out_w, out_h, calibration)
        if maps_cache is not None:
            maps_cache["_key"] = cache_key
            maps_cache["_maps"] = maps

    return apply_stitch(frame, maps)
