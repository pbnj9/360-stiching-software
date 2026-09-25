"""Tkinter GUI for the Gear 360 (2017 / SM-R210) dual-fisheye stitcher."""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
from PIL import Image, ImageTk

from .calibration import load_calibration, save_calibration, DEFAULT_PROFILE_PATH
from .image_pipeline import stitch_photos_batch
from .video_pipeline import stitch_videos_batch, ffmpeg_available
from .stitcher import stitch_frame

PHOTO_EXTS = (".jpg", ".jpeg")
VIDEO_EXTS = (".mp4",)


class StitcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gear 360 Stitcher (SM-R210, 2017)")
        self.geometry("820x600")

        self.calibration = load_calibration()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.photo_tab = BatchTab(
            notebook,
            kind="photo",
            exts=PHOTO_EXTS,
            get_calibration=lambda: self.calibration,
            batch_fn=stitch_photos_batch,
        )
        self.video_tab = BatchTab(
            notebook,
            kind="video",
            exts=VIDEO_EXTS,
            get_calibration=lambda: self.calibration,
            batch_fn=stitch_videos_batch,
        )
        self.calib_tab = CalibrationTab(notebook, self)

        notebook.add(self.photo_tab, text="Stitch Photos")
        notebook.add(self.video_tab, text="Stitch Videos")
        notebook.add(self.calib_tab, text="Calibration")


class BatchTab(ttk.Frame):
    def __init__(self, parent, kind, exts, get_calibration, batch_fn):
        super().__init__(parent)
        self.kind = kind
        self.exts = exts
        self.get_calibration = get_calibration
        self.batch_fn = batch_fn
        self.input_paths = []
        self.output_dir = ""

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text=f"Add {kind}s...", command=self.add_files).pack(side="left")
        ttk.Button(top, text="Clear list", command=self.clear_files).pack(side="left", padx=6)
        ttk.Button(top, text="Choose output folder...", command=self.choose_output).pack(
            side="left", padx=6
        )

        self.output_label = ttk.Label(self, text="Output folder: (none selected)")
        self.output_label.pack(fill="x", padx=10)

        self.listbox = tk.Listbox(self)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=10)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=10)

        if kind == "video":
            ffmpeg_ok = ffmpeg_available()
            note = (
                "ffmpeg detected: audio will be kept."
                if ffmpeg_ok
                else "ffmpeg NOT found on PATH: output video will be silent (no audio)."
            )
            ttk.Label(bottom, text=note).pack(side="left")

        self.start_button = ttk.Button(bottom, text="Start stitching", command=self.start)
        self.start_button.pack(side="right")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 5))
        self.status_label = ttk.Label(self, text="Idle")
        self.status_label.pack(fill="x", padx=10, pady=(0, 10))

        self._queue = queue.Queue()
        self.after(100, self._poll_queue)

    def add_files(self):
        filetypes = [("Supported files", " ".join(f"*{e}" for e in self.exts))]
        paths = filedialog.askopenfilenames(title=f"Select {self.kind} files", filetypes=filetypes)
        for p in paths:
            if p not in self.input_paths:
                self.input_paths.append(p)
                self.listbox.insert("end", p)

    def clear_files(self):
        self.input_paths = []
        self.listbox.delete(0, "end")

    def choose_output(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.output_dir = d
            self.output_label.config(text=f"Output folder: {d}")

    def start(self):
        if not self.input_paths:
            messagebox.showwarning("No files", f"Add at least one {self.kind} file first.")
            return
        if not self.output_dir:
            messagebox.showwarning("No output folder", "Choose an output folder first.")
            return

        self.start_button.config(state="disabled")
        self.progress.config(maximum=len(self.input_paths), value=0)
        self.status_label.config(text="Starting...")

        calibration = self.get_calibration()
        thread = threading.Thread(
            target=self._run_batch, args=(calibration,), daemon=True
        )
        thread.start()

    def _run_batch(self, calibration):
        def progress_cb(*args):
            self._queue.put(("progress", args))

        try:
            results = self.batch_fn(
                self.input_paths, self.output_dir, calibration, progress_cb=progress_cb
            )
            self._queue.put(("done", results))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("error", str(exc)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    if self.kind == "photo":
                        i, total, name = payload
                        self.progress.config(value=i)
                        self.status_label.config(text=f"[{i}/{total}] {name}")
                    else:
                        i, total, name, frame_idx, frame_total = payload
                        self.progress.config(value=i - 1 + (frame_idx / max(frame_total, 1)))
                        self.status_label.config(
                            text=f"[{i}/{total}] {name} - frame {frame_idx}/{frame_total}"
                        )
                elif kind == "done":
                    self.start_button.config(state="normal")
                    failed = [r for r in payload if r[-1]]
                    if failed:
                        self.status_label.config(
                            text=f"Done with {len(failed)} error(s). See details."
                        )
                        messagebox.showwarning(
                            "Completed with errors",
                            "\n".join(f"{r[0]}: {r[-1]}" for r in failed),
                        )
                    else:
                        self.status_label.config(text="Done.")
                        messagebox.showinfo("Done", f"Stitched {len(payload)} file(s).")
                elif kind == "error":
                    self.start_button.config(state="normal")
                    self.status_label.config(text="Error.")
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


class CalibrationTab(ttk.Frame):
    """Lets the user tweak lens calibration with a live preview and save it as
    the default profile used by both the photo and video pipelines."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.sample_frame = None
        self.preview_image_ref = None

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=10, pady=10)

        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        ttk.Button(left, text="Load sample photo/video...", command=self.load_sample).pack(
            fill="x", pady=(0, 10)
        )

        self.vars = {}
        self._build_slider(left, "front", "cx_frac", "Front center X", 0.3, 0.7)
        self._build_slider(left, "front", "cy_frac", "Front center Y", 0.3, 0.7)
        self._build_slider(left, "front", "radius_frac", "Front radius", 0.3, 0.6)
        self._build_slider(left, "front", "fov_deg", "Front FOV (deg)", 150, 220)
        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=10)
        self._build_slider(left, "back", "cx_frac", "Back center X", 0.3, 0.7)
        self._build_slider(left, "back", "cy_frac", "Back center Y", 0.3, 0.7)
        self._build_slider(left, "back", "radius_frac", "Back radius", 0.3, 0.6)
        self._build_slider(left, "back", "fov_deg", "Back FOV (deg)", 150, 220)
        self._build_slider(left, "back", "rotation_deg", "Back rotation (deg)", 0, 360)

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=10)
        ttk.Button(btns, text="Preview", command=self.update_preview).pack(side="left")
        ttk.Button(btns, text="Save profile", command=self.save_profile).pack(side="left", padx=6)
        ttk.Button(btns, text="Reset defaults", command=self.reset_defaults).pack(side="left")

        self.preview_label = ttk.Label(right, text="Load a sample file to preview stitching.")
        self.preview_label.pack(fill="both", expand=True)

    def _build_slider(self, parent, lens, field, label, lo, hi):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=label, width=18).pack(side="left")
        value = self.app.calibration[lens].get(field, (lo + hi) / 2)
        var = tk.DoubleVar(value=value)
        scale = ttk.Scale(frame, from_=lo, to=hi, variable=var, orient="horizontal")
        scale.pack(side="left", fill="x", expand=True)
        self.vars[(lens, field)] = var

    def load_sample(self):
        path = filedialog.askopenfilename(
            title="Select a Gear 360 photo or video",
            filetypes=[("Photo/Video", "*.jpg *.jpeg *.mp4")],
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in VIDEO_EXTS:
            cap = cv2.VideoCapture(path)
            mid = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) // 2)
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(mid, 0))
            ok, frame = cap.read()
            cap.release()
            if not ok:
                messagebox.showerror("Error", "Could not read a frame from that video.")
                return
            self.sample_frame = frame
        else:
            frame = cv2.imread(path, cv2.IMREAD_COLOR)
            if frame is None:
                messagebox.showerror("Error", "Could not read that image.")
                return
            self.sample_frame = frame
        self.update_preview()

    def _current_calibration(self):
        calib = {"front": {}, "back": {}, "feather_frac": self.app.calibration.get("feather_frac", 0.85)}
        for (lens, field), var in self.vars.items():
            calib[lens][field] = var.get()
        return calib

    def update_preview(self):
        if self.sample_frame is None:
            messagebox.showwarning("No sample", "Load a sample photo or video first.")
            return
        calib = self._current_calibration()
        self.app.calibration = calib
        stitched = stitch_frame(self.sample_frame, calib)

        preview = cv2.cvtColor(stitched, cv2.COLOR_BGR2RGB)
        h, w = preview.shape[:2]
        max_w = 620
        if w > max_w:
            scale = max_w / w
            preview = cv2.resize(preview, (max_w, int(h * scale)))
        img = Image.fromarray(preview)
        self.preview_image_ref = ImageTk.PhotoImage(img)
        self.preview_label.config(image=self.preview_image_ref, text="")

    def save_profile(self):
        calib = self._current_calibration()
        self.app.calibration = calib
        save_calibration(calib, DEFAULT_PROFILE_PATH)
        messagebox.showinfo("Saved", f"Calibration profile saved to:\n{DEFAULT_PROFILE_PATH}")

    def reset_defaults(self):
        from .calibration import DEFAULT_CALIBRATION

        for (lens, field), var in self.vars.items():
            var.set(DEFAULT_CALIBRATION[lens][field])
        self.update_preview()


def main():
    app = StitcherApp()
    app.mainloop()
