import os
import queue
import shutil
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    import tkinter as tk
    DND_AVAILABLE = True
except Exception:
    import tkinter as tk
    TkinterDnD = None
    DND_FILES = None
    DND_AVAILABLE = False


APP_DIR = Path(__file__).resolve().parent
CACHE_DIR = APP_DIR / "model_cache"
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".mp4", ".mov", ".mkv"}

os.environ.setdefault("HF_HOME", str(CACHE_DIR))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class AudioTranscriberApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Transcriber")
        self.root.geometry("820x620")
        self.root.minsize(720, 520)

        self.audio_path = None
        self.output_path = None
        self.transcript_text = ""
        self.worker = None
        self.events = queue.Queue()
        self.is_busy = False
        self.status_base = "Ready"
        self.status_percent = None
        self.dots = 0

        self._build_ui()
        self.root.after(120, self._process_events)
        self.root.after(500, self._animate_status)

    def _build_ui(self):
        self.root.configure(bg="#f7f7f4")
        outer = tk.Frame(self.root, bg="#f7f7f4", padx=20, pady=18)
        outer.pack(fill=tk.BOTH, expand=True)

        title_row = tk.Frame(outer, bg="#f7f7f4")
        title_row.pack(fill=tk.X)

        tk.Label(
            title_row,
            text="Audio Transcriber",
            font=("Segoe UI", 20, "bold"),
            bg="#f7f7f4",
            fg="#171717",
        ).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            title_row,
            textvariable=self.status_var,
            font=("Segoe UI", 10),
            bg="#f7f7f4",
            fg="#555555",
        ).pack(side=tk.RIGHT, padx=(12, 0))

        drop_text = "Drop an audio file here" if DND_AVAILABLE else "Choose an audio file"
        self.drop_zone = tk.Label(
            outer,
            text=drop_text,
            font=("Segoe UI", 15, "bold"),
            bg="#ffffff",
            fg="#333333",
            relief=tk.SOLID,
            bd=1,
            height=4,
        )
        self.drop_zone.pack(fill=tk.X, pady=(18, 10))

        if DND_AVAILABLE:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)

        self.file_var = tk.StringVar(value="No file selected")
        tk.Label(
            outer,
            textvariable=self.file_var,
            font=("Segoe UI", 10),
            bg="#f7f7f4",
            fg="#333333",
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        controls = tk.Frame(outer, bg="#f7f7f4")
        controls.pack(fill=tk.X)

        self.choose_button = tk.Button(
            controls,
            text="Choose File",
            command=self.choose_file,
            font=("Segoe UI", 10, "bold"),
            width=14,
            padx=8,
            pady=7,
        )
        self.choose_button.pack(side=tk.LEFT)

        tk.Label(controls, text="Model", bg="#f7f7f4", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(18, 6))
        self.model_var = tk.StringVar(value="base")
        self.model_combo = ttk.Combobox(
            controls,
            textvariable=self.model_var,
            values=("tiny", "base", "small", "medium"),
            state="readonly",
            width=10,
        )
        self.model_combo.pack(side=tk.LEFT)

        tk.Label(controls, text="Language", bg="#f7f7f4", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(18, 6))
        self.language_var = tk.StringVar(value="auto")
        self.language_combo = ttk.Combobox(
            controls,
            textvariable=self.language_var,
            values=("auto", "en", "es", "fr", "de", "pt", "it", "nl"),
            state="readonly",
            width=8,
        )
        self.language_combo.pack(side=tk.LEFT)

        self.transcribe_button = tk.Button(
            controls,
            text="Transcribe",
            command=self.start_transcription,
            font=("Segoe UI", 10, "bold"),
            bg="#1f7a4d",
            fg="#ffffff",
            activebackground="#17643e",
            activeforeground="#ffffff",
            width=14,
            padx=8,
            pady=7,
        )
        self.transcribe_button.pack(side=tk.RIGHT)

        progress_row = tk.Frame(outer, bg="#f7f7f4")
        progress_row.pack(fill=tk.X, pady=(14, 8))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100, variable=self.progress_var)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.progress_label_var = tk.StringVar(value="0%")
        tk.Label(
            progress_row,
            textvariable=self.progress_label_var,
            font=("Segoe UI", 10, "bold"),
            bg="#f7f7f4",
            fg="#333333",
            width=5,
            anchor="e",
        ).pack(side=tk.RIGHT, padx=(10, 0))

        self.work_status_var = tk.StringVar(value="Waiting for an audio file")
        tk.Label(
            outer,
            textvariable=self.work_status_var,
            font=("Segoe UI", 10),
            bg="#f7f7f4",
            fg="#555555",
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))

        output_frame = tk.Frame(outer, bg="#f7f7f4")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 10))

        self.output = tk.Text(
            output_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg="#ffffff",
            fg="#1f1f1f",
            relief=tk.SOLID,
            bd=1,
            padx=10,
            pady=10,
        )
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(output_frame, command=self.output.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output.configure(yscrollcommand=scrollbar.set)

        bottom = tk.Frame(outer, bg="#f7f7f4")
        bottom.pack(fill=tk.X)

        self.save_button = tk.Button(
            bottom,
            text="Download Transcript",
            command=self.download_transcript,
            font=("Segoe UI", 10, "bold"),
            state=tk.DISABLED,
            width=19,
            padx=8,
            pady=7,
        )
        self.save_button.pack(side=tk.LEFT)

        self.folder_button = tk.Button(
            bottom,
            text="Open Folder",
            command=self.open_folder,
            font=("Segoe UI", 10),
            state=tk.DISABLED,
            width=13,
            padx=8,
            pady=7,
        )
        self.folder_button.pack(side=tk.LEFT, padx=(10, 0))

        self._append("Choose or drop an audio/video file, then click Transcribe.\n")
        if not DND_AVAILABLE:
            self._append("Drag and drop support is not available, but Choose File works.\n")

    def _on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if files:
            self.set_audio_file(files[0])

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Choose an audio file",
            filetypes=(
                ("Audio and video files", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.wma *.mp4 *.mov *.mkv"),
                ("All files", "*.*"),
            ),
        )
        if path:
            self.set_audio_file(path)

    def set_audio_file(self, path):
        candidate = Path(path.strip("{}")).expanduser()
        if not candidate.exists():
            messagebox.showerror("File not found", str(candidate))
            return
        if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            if not messagebox.askyesno("Use this file?", "This file type is not in the usual audio list. Try it anyway?"):
                return

        self.audio_path = candidate
        self.output_path = candidate.with_name(candidate.stem + "_transcript.txt")
        self.file_var.set(str(candidate))
        self._set_status("Ready to transcribe", None)
        self.progress_var.set(0)
        self.progress_label_var.set("0%")
        self.save_button.configure(state=tk.DISABLED)
        self.folder_button.configure(state=tk.DISABLED)
        self._replace_output(f"Selected:\n{candidate}\n\nClick Transcribe to begin.\n")

    def start_transcription(self):
        if not self.audio_path:
            messagebox.showwarning("No file selected", "Choose or drop an audio file first.")
            return
        if self.worker and self.worker.is_alive():
            return

        self._set_busy(True)
        self.transcript_text = ""
        self._replace_output("")
        self.worker = threading.Thread(target=self._transcribe_worker, daemon=True)
        self.worker.start()

    def _transcribe_worker(self):
        try:
            from faster_whisper import WhisperModel

            model_name = self.model_var.get()
            language = self.language_var.get()
            language_arg = None if language == "auto" else language

            self.events.put(("progress", (2, f"Loading {model_name} model")))
            model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(CACHE_DIR / "models"))

            self.events.put(("progress", (5, "Transcribing")))
            segments, info = model.transcribe(
                str(self.audio_path),
                language=language_arg,
                vad_filter=True,
                beam_size=5,
            )

            lines = []
            detected = getattr(info, "language", None)
            duration = max(float(getattr(info, "duration", 0) or 0), 0.0)
            if detected:
                self.events.put(("append", f"Detected language: {detected}\n\n"))

            for segment in segments:
                line = f"[{self._format_time(segment.start)} - {self._format_time(segment.end)}] {segment.text.strip()}"
                lines.append(line)
                if duration:
                    percent = min(99, max(5, int((float(segment.end) / duration) * 100)))
                    self.events.put(("progress", (percent, "Transcribing")))
                self.events.put(("append", line + "\n"))

            self.transcript_text = "\n".join(lines).strip() + "\n"
            self.output_path.write_text(self.transcript_text, encoding="utf-8")
            self.events.put(("done", str(self.output_path)))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _process_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self._set_status(value, self.status_percent)
                elif kind == "progress":
                    percent, message = value
                    self.progress_var.set(percent)
                    self.progress_label_var.set(f"{int(percent)}%")
                    self._set_status(message, int(percent))
                elif kind == "append":
                    self._append(value)
                elif kind == "done":
                    self.progress_var.set(100)
                    self.progress_label_var.set("100%")
                    self._set_status("Complete", 100)
                    self.work_status_var.set("Complete - transcript ready to download")
                    self.save_button.configure(state=tk.NORMAL)
                    self.folder_button.configure(state=tk.NORMAL)
                    self._set_busy(False)
                    messagebox.showinfo("Transcription complete", f"Saved to:\n{value}")
                elif kind == "error":
                    self._set_status("Error", None)
                    self._set_busy(False)
                    messagebox.showerror("Transcription error", value)
                    self._append("\nError:\n" + value + "\n")
        except queue.Empty:
            pass
        self.root.after(120, self._process_events)

    def _set_busy(self, busy):
        state = tk.DISABLED if busy else tk.NORMAL
        self.is_busy = busy
        self.choose_button.configure(state=state)
        self.transcribe_button.configure(state=state)
        self.model_combo.configure(state="disabled" if busy else "readonly")
        self.language_combo.configure(state="disabled" if busy else "readonly")
        if busy:
            self.progress_var.set(0)
            self.progress_label_var.set("0%")
            self._set_status("Starting", 0)
        else:
            self.dots = 0

    def _set_status(self, message, percent=None):
        self.status_base = message
        self.status_percent = percent
        if percent is None:
            self.status_var.set(message)
            self.work_status_var.set(message)
        else:
            status = f"{message} {int(percent)}%"
            self.status_var.set(status)
            self.work_status_var.set(status)

    def _animate_status(self):
        if self.is_busy:
            self.dots = (self.dots + 1) % 4
            suffix = "." * self.dots
            if self.status_percent is None:
                text = f"{self.status_base}{suffix}"
            else:
                text = f"{self.status_base}{suffix} {int(self.status_percent)}%"
            self.work_status_var.set(text)
        self.root.after(500, self._animate_status)

    def _append(self, text):
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def _replace_output(self, text):
        self.output.delete("1.0", tk.END)
        self._append(text)

    def download_transcript(self):
        if not self.transcript_text:
            return
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        filename = self.output_path.name if self.output_path else "transcript.txt"
        target = self._unique_path(downloads / filename)
        target.write_text(self.transcript_text, encoding="utf-8")
        self.output_path = target
        self.folder_button.configure(state=tk.NORMAL)
        messagebox.showinfo("Downloaded", f"Transcript saved to Downloads:\n{target}")

    def open_folder(self):
        if self.output_path:
            folder = self.output_path.parent
        elif self.audio_path:
            folder = self.audio_path.parent
        else:
            return
        os.startfile(str(folder))

    @staticmethod
    def _format_time(seconds):
        total = int(seconds)
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _unique_path(path):
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1


def main():
    root_cls = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk
    root = root_cls()
    if shutil.which("ffmpeg"):
        pass
    AudioTranscriberApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
