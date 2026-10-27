# Gear 360 Stitcher (2017 SM-R210)

Windows desktop tool that converts raw dual-fisheye photos/videos from the
2017 Samsung Gear 360 (model **SM-R210**) into standard equirectangular
360 panoramas/videos.

Confirmed formats for this camera:
- Photos: `5792x2896` JPG (two 2896x2896 fisheye circles side by side).
- Videos: `2560x1280` MP4 (two 1280x1280 fisheye circles side by side).

## Setup

```powershell
cd "gear360-stitcher"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Optional but recommended for video: install **ffmpeg** and make sure it's on
your PATH (`winget install ffmpeg`). Without it, stitched videos will have no
audio track (video-only output still works).

## Run

```powershell
python main.py
```

## Windows app (.exe)

Build a standalone Windows executable from PowerShell:

```powershell
cd "gear360-stitcher"
.\build-exe.ps1
```

The app is created at `dist\Gear-360-Stitcher.exe`. Double-click it to run;
Python is not required on the computer running the executable. The first
calibration profile save is stored in
`%LOCALAPPDATA%\Gear360Stitcher\calibration_profiles\default.json`, so it
remains writable and persists across app updates. FFmpeg remains optional and
must be installed separately to preserve video audio.

## Versions

Each working release is kept as both a Git tag and a runnable snapshot under
`versions/<version>/gear360-stitcher/`:

- `versions/v0.1.0` — baseline stitching workflow.
- `versions/v0.2.0` — clean Stitch Studio interface.
- `versions/v0.2.1` — interface with the refined calibration workspace.
- `versions/v0.3.0` — live in-progress previews and main-window stitch controls.
- `versions/v0.3.1` — always-visible output picker and Start stitching action.

To run an older snapshot directly:

```powershell
cd versions\v0.1.0\gear360-stitcher
python main.py
```

The app has three tabs:

1. **Stitch Photos** — add one or more `.jpg` files, pick an output folder,
   click Start. Output files are named `<original>_360.jpg`.
2. **Stitch Videos** — same workflow for `.mp4` files. Output files are named
   `<original>_360.mp4`. If ffmpeg is on PATH, original audio is preserved.
3. **Calibration** — load a sample photo or video frame and adjust lens
   center/radius/FOV/rotation sliders with a live preview until the seam
   between the front and back lens looks correct, then **Save profile**. The
   profile is stored in `calibration_profiles/default.json` (as resolution-
   independent fractions), so it applies to both photos and videos.

Both stitching tabs also include **Quick Stitch Controls**. Adjust front/back
lens center, radius, field of view, back rotation, or seam feathering before
starting a job. These values apply to that tab's next job without replacing the
saved default calibration profile. A stitched preview is shown after each photo
finishes stitching and periodically while each video is processed.

The Calibration tab shows both the full 360 panorama and a perspective-corrected
normal view. Its sliders update both previews automatically. Use the Yaw,
Pitch, and FOV controls to aim the normal view at your subject, then select
**Export normal view** to save a standard JPG. The original `_360.jpg` or
`_360.mp4` output remains the full panorama.

## How it works

Each raw frame contains two ~195° fisheye circles (front lens on the left
half, back lens on the right half). The stitcher builds a pixel remap from
equirectangular coordinates back into each fisheye circle (equidistant/
f-theta model), then blends the overlapping edge regions between the two
lenses. Remap tables are computed once per resolution/calibration and reused
across every frame of a video for speed.

## Notes / limitations

- The default calibration assumes each lens circle is centered and fills its
  half of the frame; use the Calibration tab to fine-tune if the seam is
  visibly misaligned (this varies slightly per physical unit).
- Video stitching is CPU-based (OpenCV `remap`); very long/high-res videos
  will take a while.
