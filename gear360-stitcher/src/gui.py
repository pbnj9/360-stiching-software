"""Tkinter GUI for the Gear 360 (2017 / SM-R210) dual-fisheye stitcher."""
import os
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
from PIL import Image, ImageTk

from .calibration import load_calibration, save_calibration, DEFAULT_PROFILE_PATH
from .editor_model import EditorProject, ProjectHistory, ReframeKeyframe
from .image_pipeline import stitch_photos_batch
from .video_pipeline import stitch_videos_batch, ffmpeg_available
from .stitcher import reframe_equirect, stitch_frame

PHOTO_EXTS = (".jpg", ".jpeg")
VIDEO_EXTS = (".mp4",)
CALIBRATION_PREVIEW_WIDTH = 1280


class StitcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gear 360 Studio")
        self.geometry("1440x900")
        self.minsize(1100, 700)
        self.configure(background="#111a1d")
        self._configure_style()

        self.calibration = load_calibration()

        toolbar = ttk.Frame(self, style="Header.TFrame")
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="GEAR 360", style="Brand.TLabel").pack(
            side="left", padx=18, pady=12
        )
        ttk.Label(toolbar, text="STUDIO", style="Title.TLabel").pack(side="left")
        self.editor = EditorTab(self, self)
        self.editor.pack(fill="both", expand=True)

    def _configure_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Canvas.TFrame", background="#0b1114")
        style.configure("Header.TFrame", background="#101b20")
        style.configure("Toolbar.TFrame", background="#101b20")
        style.configure("Panel.TFrame", background="#141f24")
        style.configure("Brand.TLabel", background="#101b20", foreground="#46d9c2", font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", background="#101b20", foreground="#f2f8f7", font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background="#101b20", foreground="#8ea3a4", font=("Segoe UI", 9))
        style.configure("Toolbar.TLabel", background="#101b20", foreground="#b7c8c8", font=("Segoe UI", 9))
        style.configure("Panel.TLabelframe", background="#141f24", bordercolor="#26353b", relief="solid")
        style.configure("Panel.TLabelframe.Label", background="#141f24", foreground="#dce8e7", font=("Segoe UI", 9, "bold"))
        style.configure("TLabel", background="#141f24", foreground="#dce8e7", font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background="#141f24", foreground="#7f9899", font=("Segoe UI", 9))
        style.configure("Section.TLabel", background="#141f24", foreground="#46d9c2", font=("Segoe UI", 8, "bold"))
        style.configure("Value.TLabel", background="#141f24", foreground="#f2f8f7", font=("Cascadia Mono", 9))
        style.configure("TButton", background="#1c2a30", foreground="#dce8e7", borderwidth=0, padding=(10, 6), font=("Segoe UI", 9))
        style.map("TButton", background=[("active", "#284048"), ("disabled", "#172126")], foreground=[("disabled", "#61777a")])
        style.configure("Tool.TButton", background="#101b20", foreground="#b7c8c8", borderwidth=0, padding=(8, 5), font=("Segoe UI", 9))
        style.map("Tool.TButton", background=[("active", "#22363b")], foreground=[("active", "#f2f8f7")])
        style.configure("Primary.TButton", background="#0d907f", foreground="#ffffff", borderwidth=0, padding=(12, 7), font=("Segoe UI Semibold", 9))
        style.map("Primary.TButton", background=[("active", "#11aa96"), ("disabled", "#245d58")])
        style.configure("TCombobox", fieldbackground="#1c2a30", background="#1c2a30", foreground="#e7f2ef", arrowcolor="#46d9c2", padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#1c2a30")], foreground=[("readonly", "#e7f2ef")])
        style.configure("Horizontal.TScale", background="#141f24", troughcolor="#263940")
        style.configure("Timeline.Horizontal.TScale", background="#141f24", troughcolor="#1e4a4b")
        style.configure("TPanedwindow", background="#0b1114")
        style.configure("TSeparator", background="#26353b")
        style.configure("TProgressbar", troughcolor="#1c2a30", background="#0d907f", thickness=6)


class EditorTab(ttk.Frame):
    """Dockable single-clip 360 editor with reframing controls and a timeline."""

    def __init__(self, parent, app):
        super().__init__(parent, style="Canvas.TFrame")
        self.app = app
        self.history = ProjectHistory()
        self.duration = 0.0
        self.frame = None
        self.playing = False
        self._preview_after_id = None
        self.time_var = tk.DoubleVar()
        self.yaw_var = tk.DoubleVar()
        self.pitch_var = tk.DoubleVar()
        self.fov_var = tk.DoubleVar(value=90)
        self.trim_start_var = tk.DoubleVar()
        self.trim_end_var = tk.DoubleVar()
        self.preset_var = tk.StringVar(value="Reframed 1080p")
        self._build()
        self.bind_all("<space>", lambda _: self.toggle_playback())
        self.bind_all("<Control-z>", lambda _: self.undo())
        self.bind_all("<Control-y>", lambda _: self.redo())
        self.bind_all("<Left>", lambda _: self.step(-1))
        self.bind_all("<Right>", lambda _: self.step(1))

    def _build(self):
        actions = ttk.Frame(self, style="Toolbar.TFrame")
        actions.pack(fill="x", padx=16, pady=(8, 12))
        ttk.Button(actions, text="Import media", command=self.import_media, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Open", command=self.open_project, style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Save", command=self.save_project, style="Tool.TButton").pack(side="left")
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=10, pady=3)
        ttk.Button(actions, text="Undo", command=self.undo, style="Tool.TButton").pack(side="left")
        ttk.Button(actions, text="Redo", command=self.redo, style="Tool.TButton").pack(side="left")
        ttk.Button(actions, text="Export", command=self.export, style="Primary.TButton").pack(side="right")
        self.status = ttk.Label(actions, text="Ready to import 360 media", style="Toolbar.TLabel")
        self.status.pack(side="right", padx=16)

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        media = ttk.LabelFrame(panes, text="MEDIA", style="Panel.TLabelframe")
        center = ttk.LabelFrame(panes, text="REFRAME CANVAS", style="Panel.TLabelframe")
        inspector = ttk.LabelFrame(panes, text="INSPECTOR", style="Panel.TLabelframe")
        panes.add(media, weight=1)
        panes.add(center, weight=4)
        panes.add(inspector, weight=1)
        media_top = ttk.Frame(media, style="Panel.TFrame")
        media_top.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Label(media_top, text="PROJECT MEDIA", style="Section.TLabel").pack(side="left")
        ttk.Label(media_top, text="1 SLOT", style="Muted.TLabel").pack(side="right")
        self.media_list = tk.Listbox(
            media, background="#101a1e", foreground="#e7f2ef", selectbackground="#0d907f",
            selectforeground="#ffffff", highlightthickness=0, activestyle="none", borderwidth=0,
            font=("Segoe UI", 10), relief="flat",
        )
        self.media_list.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        ttk.Label(media, text="Import a Gear 360 photo or video to create a clip.", style="Muted.TLabel", wraplength=170).pack(anchor="w", padx=10, pady=(0, 12))

        canvas_header = ttk.Frame(center, style="Panel.TFrame")
        canvas_header.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Label(canvas_header, text="LIVE PREVIEW", style="Section.TLabel").pack(side="left")
        ttk.Label(canvas_header, text="REFRAMED 16:9", style="Muted.TLabel").pack(side="right")
        self.canvas = ttk.Label(center, text="Your reframed preview appears here", anchor="center", style="Muted.TLabel")
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        ttk.Separator(center, orient="horizontal").pack(fill="x", padx=12)
        ttk.Label(center, text="Drag the dock dividers to customize your workspace.", style="Muted.TLabel").pack(anchor="w", padx=12, pady=9)

        ttk.Label(inspector, text="REFRAME", style="Section.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        for label, var, low, high in (("Yaw", self.yaw_var, -180, 180), ("Pitch", self.pitch_var, -85, 85), ("FOV", self.fov_var, 40, 120)):
            row = ttk.Frame(inspector, style="Panel.TFrame")
            row.pack(fill="x", padx=12, pady=(10, 0))
            ttk.Label(row, text=label).pack(side="left")
            value = ttk.Label(row, style="Value.TLabel", width=7, anchor="e")
            value.pack(side="right")
            var.trace_add("write", lambda *_args, target=value, source=var: target.config(text=f"{source.get():.0f} deg"))
            ttk.Scale(inspector, from_=low, to=high, variable=var, command=self.schedule_preview).pack(fill="x", padx=12)
        ttk.Button(inspector, text="Add keyframe", command=self.add_keyframe, style="Primary.TButton").pack(fill="x", padx=12, pady=16)
        ttk.Separator(inspector, orient="horizontal").pack(fill="x", padx=12)
        ttk.Label(inspector, text="EXPORT", style="Section.TLabel").pack(anchor="w", padx=12, pady=(14, 0))
        ttk.Label(inspector, text="Preset", style="Muted.TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Combobox(inspector, textvariable=self.preset_var, state="readonly",
                     values=("Reframed 1080p", "Reframed 720p", "Full 360")).pack(fill="x", padx=12, pady=(3, 12))
        ttk.Label(inspector, text="Advanced calibration is available from the source workflow.", style="Muted.TLabel", wraplength=180).pack(anchor="w", padx=12, pady=(10, 0))

        timeline = ttk.LabelFrame(self, text="TIMELINE", style="Panel.TLabelframe")
        timeline.pack(fill="x", padx=16, pady=(0, 16))
        controls = ttk.Frame(timeline, style="Panel.TFrame")
        controls.pack(fill="x", padx=10, pady=(9, 3))
        ttk.Button(controls, text="Play", command=self.toggle_playback, style="Primary.TButton").pack(side="left")
        ttk.Button(controls, text="Set In", command=lambda: self.set_trim(True), style="Tool.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Set Out", command=lambda: self.set_trim(False), style="Tool.TButton").pack(side="left")
        ttk.Label(controls, text="Single-clip timeline", style="Muted.TLabel").pack(side="right")
        self.timeline = ttk.Scale(timeline, from_=0, to=1, variable=self.time_var, command=self.schedule_preview, style="Timeline.Horizontal.TScale")
        self.timeline.pack(fill="x", padx=14, pady=(3, 10))
        self.keyframes_label = ttk.Label(timeline, text="No keyframes", style="Muted.TLabel")
        self.keyframes_label.pack(anchor="e", padx=14, pady=(0, 8))

    def import_media(self):
        path = filedialog.askopenfilename(filetypes=[("Gear 360 media", "*.jpg *.jpeg *.mp4")])
        if not path: return
        self.history.snapshot()
        kind = "video" if os.path.splitext(path)[1].lower() in VIDEO_EXTS else "photo"
        self.history.project = EditorProject(media_path=path, media_kind=kind, export_preset=self.preset_var.get())
        self.media_list.delete(0, "end"); self.media_list.insert("end", os.path.basename(path))
        if kind == "video":
            cap = cv2.VideoCapture(path); self.duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1); cap.release()
        else: self.duration = 0
        self.trim_end_var.set(self.duration); self.timeline.config(to=max(self.duration, 1)); self.render()

    def _source_frame(self):
        project = self.history.project
        if project.media_kind == "video":
            cap = cv2.VideoCapture(project.media_path); cap.set(cv2.CAP_PROP_POS_MSEC, self.time_var.get() * 1000); ok, frame = cap.read(); cap.release()
            return frame if ok else None
        return cv2.imread(project.media_path, cv2.IMREAD_COLOR)

    def schedule_preview(self, *_):
        if self._preview_after_id: self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(80, self.render)

    def render(self):
        self._preview_after_id = None
        frame = self._source_frame()
        if frame is None: return
        scale = min(1280 / frame.shape[1], 1); frame = cv2.resize(frame, (round(frame.shape[1]*scale), round(frame.shape[0]*scale))) if scale < 1 else frame
        stitched = stitch_frame(frame, self.app.calibration)
        view = reframe_equirect(stitched, self.yaw_var.get(), self.pitch_var.get(), self.fov_var.get(), out_w=720)
        image = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(view, cv2.COLOR_BGR2RGB)))
        self.canvas.configure(image=image, text=""); self.canvas.image = image
        self.status.configure(text=f"{os.path.basename(self.history.project.media_path)}  {self.time_var.get():.2f}s")

    def add_keyframe(self):
        self.history.snapshot(); project = self.history.project
        project.keyframes = [keyframe for keyframe in project.keyframes if abs(keyframe.time_seconds - self.time_var.get()) > .01]
        project.keyframes.append(ReframeKeyframe(self.time_var.get(), self.yaw_var.get(), self.pitch_var.get(), self.fov_var.get()))
        project.keyframes.sort(); self.keyframes_label.config(text=f"{len(project.keyframes)} keyframe(s)")

    def set_trim(self, is_start):
        self.history.snapshot()
        if is_start: self.history.project.trim_start = self.time_var.get()
        else: self.history.project.trim_end = self.time_var.get()

    def toggle_playback(self):
        if not self.history.project.media_path or self.history.project.media_kind != "video": return
        self.playing = not self.playing
        if self.playing: self._play()

    def _play(self):
        if not self.playing: return
        current = self.time_var.get() + 1 / 30
        if current > self.history.project.trim_end: current = self.history.project.trim_start
        self.time_var.set(current); view = self.history.project.view_at(current)
        self.yaw_var.set(view.yaw_deg); self.pitch_var.set(view.pitch_deg); self.fov_var.set(view.fov_deg)
        self.render(); self.after(33, self._play)

    def step(self, direction):
        self.time_var.set(max(0, min(self.duration, self.time_var.get() + direction / 30))); self.render()

    def undo(self):
        if self.history.undo(): self._restore_project()

    def redo(self):
        if self.history.redo(): self._restore_project()

    def _restore_project(self):
        project = self.history.project; self.preset_var.set(project.export_preset); self.time_var.set(project.trim_start); self.render()

    def save_project(self):
        path = filedialog.asksaveasfilename(defaultextension=".gear360project", filetypes=[("Gear 360 project", "*.gear360project")])
        if path: self.history.project.export_preset = self.preset_var.get(); self.history.save(path)

    def open_project(self):
        path = filedialog.askopenfilename(filetypes=[("Gear 360 project", "*.gear360project")])
        if not path: return
        try: self.history.load(path)
        except (OSError, ValueError, json.JSONDecodeError) as error: messagebox.showerror("Project error", str(error)); return
        self.import_loaded_project()

    def import_loaded_project(self):
        project = self.history.project; self.media_list.delete(0, "end"); self.media_list.insert("end", os.path.basename(project.media_path))
        self.import_media_metadata()

    def import_media_metadata(self):
        project = self.history.project
        if project.media_kind == "video":
            cap = cv2.VideoCapture(project.media_path); self.duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1); cap.release()
        self.timeline.config(to=max(self.duration, 1)); self.time_var.set(project.trim_start); self.render()

    def export(self):
        if not self.history.project.media_path:
            messagebox.showwarning("No media", "Import media before exporting.")
            return
        messagebox.showinfo(
            "Export settings",
            f"{self.preset_var.get()} is selected.\n"
            "Photo export remains available in the Calibration workspace; "
            "timeline video rendering will be added next.",
        )


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
