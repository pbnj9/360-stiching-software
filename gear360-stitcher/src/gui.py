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
from .stitcher import reframe_equirect, stitch_frame

PHOTO_EXTS = (".jpg", ".jpeg")
VIDEO_EXTS = (".mp4",)
CALIBRATION_PREVIEW_WIDTH = 1280


class StitcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gear 360 Stitcher - v0.3.1")
        self.geometry("1100x720")
        self.minsize(900, 620)
        self.configure(background="#edf1ee")
        self._configure_style()

        self.calibration = load_calibration()

        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(fill="x")
        title_area = ttk.Frame(header, style="Header.TFrame")
        title_area.pack(fill="x", padx=28, pady=(20, 18))
        ttk.Label(title_area, text="GEAR 360", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(title_area, text="Stitch Studio", style="Title.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(
            title_area,
            text="Samsung Gear 360 (2017 / SM-R210) dual-fisheye conversion",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        content = ttk.Frame(self, style="Canvas.TFrame")
        content.pack(fill="both", expand=True, padx=22, pady=(18, 12))
        notebook = ttk.Notebook(self)
        notebook.pack(in_=content, fill="both", expand=True)

        self.photo_tab = BatchTab(
            notebook,
            kind="photo",
            exts=PHOTO_EXTS,
            get_calibration=lambda: self.calibration,
            set_calibration=lambda calibration: setattr(self, "calibration", calibration),
            batch_fn=stitch_photos_batch,
        )
        self.video_tab = BatchTab(
            notebook,
            kind="video",
            exts=VIDEO_EXTS,
            get_calibration=lambda: self.calibration,
            set_calibration=lambda calibration: setattr(self, "calibration", calibration),
            batch_fn=stitch_videos_batch,
        )
        self.calib_tab = CalibrationTab(notebook, self)

        notebook.add(self.photo_tab, text="Stitch Photos")
        notebook.add(self.video_tab, text="Stitch Videos")
        notebook.add(self.calib_tab, text="Calibration")

        ttk.Label(
            self,
            text="Version 0.3.1  |  Equirectangular output  |  Local processing",
            style="Footer.TLabel",
        ).pack(anchor="w", padx=28, pady=(0, 12))

    def _configure_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Canvas.TFrame", background="#edf1ee")
        style.configure("Header.TFrame", background="#133b36")
        style.configure("Brand.TLabel", background="#133b36", foreground="#f3b64a", font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", background="#133b36", foreground="#ffffff", font=("Georgia", 25, "bold"))
        style.configure("Subtitle.TLabel", background="#133b36", foreground="#c6d7d3", font=("Segoe UI", 10))
        style.configure("Footer.TLabel", background="#edf1ee", foreground="#59706a", font=("Segoe UI", 9))
        style.configure("TNotebook", background="#edf1ee", borderwidth=0)
        style.configure("TNotebook.Tab", background="#d9e2de", foreground="#29423d", padding=(18, 10), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#0b5d52")])
        style.configure("Workspace.TFrame", background="#ffffff")
        style.configure("Panel.TLabelframe", background="#ffffff", bordercolor="#cbd7d2", relief="solid")
        style.configure("Panel.TLabelframe.Label", background="#ffffff", foreground="#133b36", font=("Segoe UI", 11, "bold"))
        style.configure("TLabel", background="#ffffff", foreground="#29423d", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#647873", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#ffffff", foreground="#0b5d52", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=(12, 7), font=("Segoe UI", 10))
        style.configure("Primary.TButton", background="#0b7567", foreground="#ffffff", borderwidth=0, padding=(16, 8), font=("Segoe UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#075c51"), ("disabled", "#9ebbb5")])
        style.configure("TProgressbar", troughcolor="#dbe5e1", background="#0b7567", thickness=8)
        style.configure("Horizontal.TScale", background="#ffffff", troughcolor="#dbe5e1")


class BatchTab(ttk.Frame):
    def __init__(self, parent, kind, exts, get_calibration, set_calibration, batch_fn):
        super().__init__(parent)
        self.configure(style="Workspace.TFrame")
        self.kind = kind
        self.exts = exts
        self.get_calibration = get_calibration
        self.set_calibration = set_calibration
        self.batch_fn = batch_fn
        self.input_paths = []
        self.output_dir = ""
        self.control_vars = {}
        self.preview_image_ref = None

        top_area = ttk.Frame(self, style="Workspace.TFrame")
        top_area.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        source_panel = ttk.LabelFrame(top_area, text="SOURCE FILES", style="Panel.TLabelframe")
        source_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        source_actions = ttk.Frame(source_panel, style="Workspace.TFrame")
        source_actions.pack(fill="x", padx=14, pady=(12, 6))

        ttk.Label(
            source_actions,
            text=f"Add one or more dual-fisheye {kind} files to the job.",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(
            source_actions, text=f"Add {kind}s", command=self.add_files
        ).pack(side="right")
        ttk.Button(source_actions, text="Clear", command=self.clear_files).pack(
            side="right", padx=(0, 8)
        )
        ttk.Button(
            source_actions, text="Choose output", command=self.choose_output
        ).pack(side="right", padx=(0, 8))
        self.start_button = ttk.Button(
            source_actions,
            text="Start stitching",
            command=self.start,
            style="Primary.TButton",
        )
        self.start_button.pack(side="right", padx=(0, 8))

        self.listbox = tk.Listbox(
            source_panel,
            activestyle="none",
            background="#f7f9f8",
            borderwidth=0,
            font=("Segoe UI", 10),
            foreground="#29423d",
            highlightthickness=1,
            highlightbackground="#d3ded9",
            selectbackground="#b8d9d1",
            selectforeground="#133b36",
        )
        self.listbox.pack(fill="both", expand=True, padx=14, pady=(4, 14))

        preview_panel = ttk.LabelFrame(
            top_area, text="LIVE STITCH PREVIEW", style="Panel.TLabelframe"
        )
        preview_panel.pack(side="right", fill="both", expand=True)
        self.preview_label = ttk.Label(
            preview_panel,
            text="Start a job to see the stitched output here.",
            style="Muted.TLabel",
            anchor="center",
        )
        self.preview_label.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        self.preview_status = ttk.Label(
            preview_panel, text="No preview yet", style="Muted.TLabel", anchor="center"
        )
        self.preview_status.pack(fill="x", padx=14, pady=(0, 14))

        controls_panel = ttk.LabelFrame(
            self, text="QUICK STITCH CONTROLS", style="Panel.TLabelframe"
        )
        controls_panel.pack(fill="x", padx=20, pady=(0, 10))
        controls_body = ttk.Frame(controls_panel, style="Workspace.TFrame")
        controls_body.pack(fill="x", padx=14, pady=(8, 4))

        front_controls = ttk.Frame(controls_body, style="Workspace.TFrame")
        front_controls.pack(side="left", fill="both", expand=True, padx=(0, 14))
        back_controls = ttk.Frame(controls_body, style="Workspace.TFrame")
        back_controls.pack(side="left", fill="both", expand=True, padx=(0, 14))
        blend_controls = ttk.Frame(controls_body, style="Workspace.TFrame")
        blend_controls.pack(side="left", fill="both", expand=True)

        ttk.Label(front_controls, text="FRONT LENS", style="Muted.TLabel").pack(anchor="w")
        self._build_stitch_control(front_controls, "front", "cx_frac", "Center X", 0.3, 0.7)
        self._build_stitch_control(front_controls, "front", "cy_frac", "Center Y", 0.3, 0.7)
        self._build_stitch_control(front_controls, "front", "radius_frac", "Radius", 0.3, 0.6)
        self._build_stitch_control(front_controls, "front", "fov_deg", "FOV", 150, 220)

        ttk.Label(back_controls, text="BACK LENS", style="Muted.TLabel").pack(anchor="w")
        self._build_stitch_control(back_controls, "back", "cx_frac", "Center X", 0.3, 0.7)
        self._build_stitch_control(back_controls, "back", "cy_frac", "Center Y", 0.3, 0.7)
        self._build_stitch_control(back_controls, "back", "radius_frac", "Radius", 0.3, 0.6)
        self._build_stitch_control(back_controls, "back", "fov_deg", "FOV", 150, 220)
        self._build_stitch_control(back_controls, "back", "rotation_deg", "Rotation", 0, 360)

        ttk.Label(blend_controls, text="SEAM BLEND", style="Muted.TLabel").pack(anchor="w")
        self._build_stitch_control(blend_controls, "blend", "feather_frac", "Feather", 0.65, 0.95)
        ttk.Label(
            blend_controls,
            text="Changes apply to the next job.",
            style="Muted.TLabel",
            wraplength=190,
        ).pack(anchor="w", pady=(10, 4))
        ttk.Button(blend_controls, text="Reset controls", command=self.reset_controls).pack(
            anchor="w"
        )

        output_panel = ttk.Frame(self, style="Workspace.TFrame")
        output_panel.pack(fill="x", padx=20, pady=(0, 8))
        self.output_label = ttk.Label(
            output_panel, text="Output: no destination selected", style="Muted.TLabel"
        )
        self.output_label.pack(side="left")

        bottom = ttk.Frame(self, style="Workspace.TFrame")
        bottom.pack(fill="x", padx=20, pady=(0, 14))

        if kind == "video":
            ffmpeg_ok = ffmpeg_available()
            note = (
                "ffmpeg detected: audio will be kept."
                if ffmpeg_ok
                else "ffmpeg NOT found on PATH: output video will be silent (no audio)."
            )
            ttk.Label(bottom, text=note, style="Muted.TLabel").pack(side="left")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=20, pady=(0, 6))
        self.status_label = ttk.Label(self, text="Ready to stitch", style="Status.TLabel")
        self.status_label.pack(fill="x", padx=20, pady=(0, 18))

        self._queue = queue.Queue()
        self.after(100, self._poll_queue)

    def _build_stitch_control(self, parent, lens, field, label, lo, hi):
        frame = ttk.Frame(parent, style="Workspace.TFrame")
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=label, width=10).pack(side="left")
        if lens == "blend":
            value = self.get_calibration().get(field, (lo + hi) / 2)
        else:
            value = self.get_calibration()[lens].get(field, (lo + hi) / 2)
        var = tk.DoubleVar(value=value)
        ttk.Scale(frame, from_=lo, to=hi, variable=var, orient="horizontal").pack(
            side="left", fill="x", expand=True
        )
        self.control_vars[(lens, field)] = var

    def _current_calibration(self):
        calibration = {"front": {}, "back": {}, "feather_frac": 0.85}
        for (lens, field), var in self.control_vars.items():
            if lens == "blend":
                calibration[field] = var.get()
            else:
                calibration[lens][field] = var.get()
        return calibration

    def reset_controls(self):
        calibration = load_calibration()
        for (lens, field), var in self.control_vars.items():
            value = calibration.get(field) if lens == "blend" else calibration[lens][field]
            var.set(value)

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
            self.output_label.config(text=f"Output: {d}")

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

        calibration = self._current_calibration()
        self.set_calibration(calibration)
        self.preview_image_ref = None
        self.preview_label.config(image="", text="Waiting for the first stitched frame...")
        self.preview_status.config(text="Preview updates while processing")
        thread = threading.Thread(
            target=self._run_batch, args=(calibration,), daemon=True
        )
        thread.start()

    def _run_batch(self, calibration):
        def progress_cb(*args):
            self._queue.put(("progress", args))

        def preview_cb(frame, label):
            self._queue.put(("preview", (frame, label)))

        try:
            results = self.batch_fn(
                self.input_paths,
                self.output_dir,
                calibration,
                progress_cb=progress_cb,
                preview_cb=preview_cb,
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
                elif kind == "preview":
                    self._show_preview(*payload)
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

    def _show_preview(self, frame, label):
        preview = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = preview.shape[:2]
        max_width, max_height = 430, 220
        scale = min(max_width / width, max_height / height, 1.0)
        if scale < 1.0:
            preview = cv2.resize(preview, (int(width * scale), int(height * scale)))
        self.preview_image_ref = ImageTk.PhotoImage(Image.fromarray(preview))
        self.preview_label.config(image=self.preview_image_ref, text="")
        self.preview_status.config(text=label)


class CalibrationTab(ttk.Frame):
    """Lets the user tweak lens calibration with a live preview and save it as
    the default profile used by both the photo and video pipelines."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.configure(style="Workspace.TFrame")
        self.app = app
        self.sample_frame = None
        self.preview_frame = None
        self.preview_image_ref = None
        self.view_image_ref = None
        self._preview_after_id = None

        left = ttk.LabelFrame(self, text="LENS PROFILE", style="Panel.TLabelframe")
        left.pack(side="left", fill="y", padx=(20, 10), pady=20)

        right = ttk.LabelFrame(self, text="360 PANORAMA AND NORMAL VIEW", style="Panel.TLabelframe")
        right.pack(side="right", fill="both", expand=True, padx=(0, 20), pady=20)

        ttk.Button(left, text="Load sample photo/video...", command=self.load_sample).pack(
            fill="x", padx=14, pady=(14, 8)
        )
        ttk.Label(
            left,
            text="Adjust any slider to update both previews automatically.",
            style="Muted.TLabel",
            wraplength=285,
        ).pack(fill="x", padx=14, pady=(0, 10))

        self.vars = {}
        self._build_slider(left, "front", "cx_frac", "Front center X", 0.3, 0.7)
        self._build_slider(left, "front", "cy_frac", "Front center Y", 0.3, 0.7)
        self._build_slider(left, "front", "radius_frac", "Front radius", 0.3, 0.6)
        self._build_slider(left, "front", "fov_deg", "Front FOV (deg)", 150, 220)
        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=14, pady=10)
        self._build_slider(left, "back", "cx_frac", "Back center X", 0.3, 0.7)
        self._build_slider(left, "back", "cy_frac", "Back center Y", 0.3, 0.7)
        self._build_slider(left, "back", "radius_frac", "Back radius", 0.3, 0.6)
        self._build_slider(left, "back", "fov_deg", "Back FOV (deg)", 150, 220)
        self._build_slider(left, "back", "rotation_deg", "Back rotation (deg)", 0, 360)
        self.view_vars = {}

        btns = ttk.Frame(left)
        btns.pack(fill="x", padx=14, pady=(10, 14))
        ttk.Button(btns, text="Export normal view", command=self.export_normal_view).pack(side="right")
        ttk.Button(btns, text="Save profile", command=self.save_profile, style="Primary.TButton").pack(side="right", padx=(0, 8))

        self.preview_label = ttk.Label(
            right,
            text="Load a photo or video to inspect the 360 stitch and normal view.",
            style="Muted.TLabel",
            anchor="center",
        )
        self.preview_label.pack(fill="x", padx=14, pady=(14, 7))
        view_controls = ttk.Frame(right, style="Workspace.TFrame")
        view_controls.pack(fill="x", padx=14, pady=(0, 7))
        ttk.Label(view_controls, text="NORMAL VIEW", style="Muted.TLabel").pack(
            side="left", padx=(0, 12)
        )
        self._build_view_slider(view_controls, "Yaw", -180, 180, 0)
        self._build_view_slider(view_controls, "Pitch", -85, 85, 0)
        self._build_view_slider(view_controls, "FOV", 40, 120, 90)
        self.view_label = ttk.Label(
            right, text="", style="Muted.TLabel", anchor="center"
        )
        self.view_label.pack(fill="x", padx=14, pady=(7, 14))

    def _build_slider(self, parent, lens, field, label, lo, hi):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=14, pady=3)
        ttk.Label(frame, text=label, width=18).pack(side="left")
        value = self.app.calibration[lens].get(field, (lo + hi) / 2)
        var = tk.DoubleVar(value=value)
        scale = ttk.Scale(frame, from_=lo, to=hi, variable=var, orient="horizontal")
        scale.pack(side="left", fill="x", expand=True)
        self.vars[(lens, field)] = var
        var.trace_add("write", self._schedule_preview)

    def _build_view_slider(self, parent, label, lo, hi, value):
        frame = ttk.Frame(parent)
        frame.pack(side="left", fill="x", expand=True, padx=3)
        ttk.Label(frame, text=label).pack(side="left")
        var = tk.DoubleVar(value=value)
        ttk.Scale(frame, from_=lo, to=hi, variable=var, orient="horizontal").pack(
            side="left", fill="x", expand=True
        )
        self.view_vars[label] = var
        var.trace_add("write", self._schedule_preview)

    def _schedule_preview(self, *_):
        if self.preview_frame is None:
            return
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(100, self._run_scheduled_preview)

    def _run_scheduled_preview(self):
        self._preview_after_id = None
        self.update_preview()

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
        height, width = self.sample_frame.shape[:2]
        if width > CALIBRATION_PREVIEW_WIDTH:
            scale = CALIBRATION_PREVIEW_WIDTH / width
            self.preview_frame = cv2.resize(
                self.sample_frame, (CALIBRATION_PREVIEW_WIDTH, round(height * scale))
            )
        else:
            self.preview_frame = self.sample_frame
        self.update_preview()

    def _current_calibration(self):
        calib = {"front": {}, "back": {}, "feather_frac": self.app.calibration.get("feather_frac", 0.85)}
        for (lens, field), var in self.vars.items():
            calib[lens][field] = var.get()
        return calib

    def update_preview(self):
        if self.preview_frame is None:
            messagebox.showwarning("No sample", "Load a sample photo or video first.")
            return
        calib = self._current_calibration()
        self.app.calibration = calib
        stitched = stitch_frame(self.preview_frame, calib)

        preview = cv2.cvtColor(stitched, cv2.COLOR_BGR2RGB)
        h, w = preview.shape[:2]
        max_w = 420
        if w > max_w:
            scale = max_w / w
            preview = cv2.resize(preview, (max_w, int(h * scale)))
        img = Image.fromarray(preview)
        self.preview_image_ref = ImageTk.PhotoImage(img)
        self.preview_label.config(image=self.preview_image_ref, text="")
        normal_view = self._normal_view(stitched)
        normal_view = cv2.cvtColor(normal_view, cv2.COLOR_BGR2RGB)
        normal_view = cv2.resize(normal_view, (320, 180))
        self.view_image_ref = ImageTk.PhotoImage(Image.fromarray(normal_view))
        self.view_label.config(image=self.view_image_ref, text="")

    def _normal_view(self, stitched):
        return reframe_equirect(
            stitched,
            yaw_deg=self.view_vars["Yaw"].get(),
            pitch_deg=self.view_vars["Pitch"].get(),
            fov_deg=self.view_vars["FOV"].get(),
        )

    def export_normal_view(self):
        if self.sample_frame is None:
            messagebox.showwarning("No sample", "Load a sample photo or video first.")
            return
        stitched = stitch_frame(self.sample_frame, self._current_calibration())
        initial_name = "gear360_normal_view.jpg"
        path = filedialog.asksaveasfilename(
            title="Save normal view",
            defaultextension=".jpg",
            initialfile=initial_name,
            filetypes=[("JPEG image", "*.jpg")],
        )
        if not path:
            return
        if not cv2.imwrite(path, self._normal_view(stitched), [cv2.IMWRITE_JPEG_QUALITY, 95]):
            messagebox.showerror("Export failed", f"Could not write:\n{path}")
            return
        messagebox.showinfo("Exported", f"Normal view saved to:\n{path}")

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
