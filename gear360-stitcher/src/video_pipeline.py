"""Batch video stitching pipeline: dual-fisheye MP4 -> equirectangular MP4.

OpenCV's VideoWriter does not handle audio, so this pipeline writes a silent
stitched video first, then (if ffmpeg is available on PATH) remuxes the
original audio track onto the result. If ffmpeg is not available, the output
video is silent and a note is reported back to the caller.
"""
import os
import shutil
import subprocess
import tempfile

import cv2

from .stitcher import stitch_frame


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def stitch_video(
    input_path,
    output_path,
    calibration,
    out_w=None,
    out_h=None,
    frame_progress_cb=None,
):
    """Stitch one video. frame_progress_cb(frame_index, total_frames) is called
    periodically. Returns (output_path, audio_muxed: bool)."""
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {input_path}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 29.97
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    out_w = out_w or src_w
    out_h = out_h or src_h

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    use_ffmpeg = ffmpeg_available()
    silent_path = output_path
    tmp_dir = None
    if use_ffmpeg:
        tmp_dir = tempfile.mkdtemp(prefix="gear360_")
        silent_path = os.path.join(tmp_dir, "silent.mp4")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        cap.release()
        raise IOError("Failed to open video writer (codec unavailable)")

    maps_cache = {}
    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            stitched = stitch_frame(
                frame, calibration, out_w=out_w, out_h=out_h, maps_cache=maps_cache
            )
            writer.write(stitched)
            frame_index += 1
            if frame_progress_cb:
                frame_progress_cb(frame_index, total_frames)
    finally:
        cap.release()
        writer.release()

    audio_muxed = False
    if use_ffmpeg:
        audio_muxed = _mux_audio(input_path, silent_path, output_path)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return output_path, audio_muxed


def _mux_audio(original_path, silent_video_path, final_output_path):
    """Copy audio from original_path onto silent_video_path, writing final_output_path.
    Falls back to a plain (silent) copy if the source has no audio stream."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        silent_video_path,
        "-i",
        original_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        final_output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and os.path.isfile(final_output_path):
        return True
    # Fallback: no audio stream or ffmpeg error, just move the silent video.
    shutil.copyfile(silent_video_path, final_output_path)
    return False


def stitch_videos_batch(input_paths, output_dir, calibration, progress_cb=None):
    """Stitch a list of videos. progress_cb(index, total, filename, frame, frame_total)
    is called during processing."""
    total = len(input_paths)
    results = []
    for i, path in enumerate(input_paths):
        name = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(output_dir, f"{name}_360.mp4")

        def frame_cb(frame_idx, frame_total, _i=i, _path=path):
            if progress_cb:
                progress_cb(_i + 1, total, os.path.basename(_path), frame_idx, frame_total)

        try:
            _, audio_muxed = stitch_video(path, out_path, calibration, frame_progress_cb=frame_cb)
            results.append((path, out_path, audio_muxed, None))
        except Exception as exc:  # noqa: BLE001 - report per-file errors, keep going
            results.append((path, None, False, str(exc)))
    return results
