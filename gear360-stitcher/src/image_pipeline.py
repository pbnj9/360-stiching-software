"""Batch photo stitching pipeline: dual-fisheye JPG -> equirectangular JPG."""
import os
import cv2

from .stitcher import stitch_frame


def stitch_photo(input_path, output_path, calibration, out_w=None, out_h=None):
    frame = cv2.imread(input_path, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"Could not read image: {input_path}")

    result = stitch_frame(frame, calibration, out_w=out_w, out_h=out_h)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    ok = cv2.imwrite(output_path, result, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise IOError(f"Failed to write output image: {output_path}")
    return output_path


def stitch_photos_batch(input_paths, output_dir, calibration, progress_cb=None):
    """Stitch a list of photos. progress_cb(index, total, filename) is called
    after each file completes."""
    total = len(input_paths)
    results = []
    for i, path in enumerate(input_paths):
        name = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(output_dir, f"{name}_360.jpg")
        try:
            stitch_photo(path, out_path, calibration)
            results.append((path, out_path, None))
        except Exception as exc:  # noqa: BLE001 - report per-file errors, keep going
            results.append((path, None, str(exc)))
        if progress_cb:
            progress_cb(i + 1, total, os.path.basename(path))
    return results
