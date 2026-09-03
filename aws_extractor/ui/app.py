from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from aws_extractor.config import APP_NAME, Settings
from aws_extractor.core.drive import GoogleDriveUploader
from aws_extractor.core.extractor import Extractor
from aws_extractor.utils import (
    enable_windows_dpi_awareness,
    safe_name,
    windows_scale_factor,
    windows_work_area,
)


class App(tk.Tk):
    BG = "#f4f5f7"
    WHITE = "#ffffff"
    TEXT = "#111111"
    BORDER = "#d4d8dd"
    BLUE = "#1673d5"
    BLUE_ACTIVE = "#1165bd"
    GREEN = "#1fbe63"
    GREEN_ACTIVE = "#18a956"
    PURPLE = "#7c57e3"
    RED = "#d93025"
    RED_ACTIVE = "#b5251c"

    BASE_W = 1140
    BASE_H = 670
    BASE_MIN_W = 960
    BASE_MIN_H = 620

    def __init__(self, settings: Settings | None = None):
        super().__init__()

        script_dir = Path(__file__).resolve().parent.parent.parent
        self.settings = settings or Settings(script_dir)

        self.scale = windows_scale_factor() if os.name == "nt" else 1.0
        if not self.scale or self.scale <= 0:
            self.scale = 1.0

        try:
            self.tk.call("tk", "scaling", (96.0 * self.scale) / 72.0)
        except Exception:
            pass

        self.title(APP_NAME)

        win_w = self._px(self.BASE_W)
        win_h = self._px(self.BASE_H)
        self.update_idletasks()

        work_area = windows_work_area()
        if work_area:
            work_w, work_h = work_area
        else:
            work_w = self.winfo_screenwidth()
            work_h = self.winfo_screenheight()

        win_w = min(win_w, work_w)
        win_h = min(win_h, work_h)

        pos_x = max(0, (work_w - win_w) // 2)
        pos_y = max(0, (work_h - win_h) // 2)
        self.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.minsize(self._px(self.BASE_MIN_W), self._px(self.BASE_MIN_H))
        try:
            self.maxsize(work_w, work_h)
        except Exception:
            pass
        self.configure(bg=self.BG)

        self.home_var = tk.StringVar(value=self.settings.home_url)
        self.module_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(self.settings.output_dir))

        self.login_done_event = threading.Event()
        self.login_in_progress = False
        self.cancel_event = threading.Event()
        self.download_in_progress = False

        self._configure_styles()

        self.extractor = Extractor(
            settings=self.settings,
            log_callback=self._thread_log,
            progress_callback=self._thread_progress,
            sub_progress_callback=self._thread_sub_progress,
        )

        self.drive_uploader = GoogleDriveUploader(
            self.settings.base_dir,
            self._thread_log,
        )

        self._build()

    def _px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        style.configure(
            "App.TEntry",
            font=("Segoe UI", 11),
            padding=self._px(4),
        )
        style.configure(
            "App.TCombobox",
            font=("Segoe UI", 11),
            padding=self._px(2),
        )
        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor="#e6e8eb",
            background="#19b358",
            bordercolor="#d8dce0",
            lightcolor="#19b358",
            darkcolor="#19b358",
        )

    def _build(self):
        root = tk.Frame(self, bg=self.BG, padx=self._px(15), pady=self._px(8))
        root.pack(fill="both", expand=True)

        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(0, weight=0)   # título
        root.grid_rowconfigure(1, weight=0)   # módulo / salida
        root.grid_rowconfigure(2, weight=0)   # separador
        root.grid_rowconfigure(3, weight=0)   # URLs + ayuda
        root.grid_rowconfigure(4, weight=0)   # botones
        root.grid_rowconfigure(5, weight=0)   # progreso
        root.grid_rowconfigure(6, weight=1, minsize=self._px(190))  # LOG

        # -------------------------------------------------------------
        # Título
        # -------------------------------------------------------------
        title_row = tk.Frame(root, bg=self.BG)
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, self._px(6)))
        title_row.grid_columnconfigure(0, weight=1)

        tk.Label(
            title_row,
            text="AWS Academy - Extractor de material",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI", 19, "bold"),
        ).grid(row=0, column=0, sticky="w")

        # -------------------------------------------------------------
        # Módulo / salida
        # -------------------------------------------------------------
        top = tk.Frame(root, bg=self.BG)
        top.grid(row=1, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        tk.Label(
            top,
            text="Módulo / curso:",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="w", padx=(0, self._px(10)), pady=self._px(2))

        module_box_frame = tk.Frame(top, bg=self.BG)
        module_box_frame.grid(row=0, column=1, sticky="ew", pady=self._px(2))
        module_box_frame.grid_columnconfigure(0, weight=1)

        self.module_combo = ttk.Combobox(
            module_box_frame,
            textvariable=self.module_var,
            style="App.TCombobox",
            font=("Segoe UI", 10),
        )
        self.module_combo.grid(row=0, column=0, sticky="ew")

        self.list_modules_btn = ttk.Button(
            top,
            text="🔄 Listar módulos",
            command=self._list_modules,
        )
        self.list_modules_btn.grid(row=0, column=2, padx=(self._px(10), 0), pady=self._px(2))

        tk.Label(
            top,
            text="Carpeta de salida:",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI", 11),
        ).grid(row=1, column=0, sticky="w", padx=(0, self._px(10)), pady=self._px(2))

        ttk.Entry(
            top,
            textvariable=self.output_var,
            style="App.TEntry",
        ).grid(row=1, column=1, sticky="ew", pady=self._px(2))

        ttk.Button(
            top,
            text="Examinar...",
            command=self._choose_output,
        ).grid(row=1, column=2, padx=(self._px(10), 0), pady=self._px(2))

        ttk.Separator(root, orient="horizontal").grid(
            row=2, column=0, sticky="ew", pady=(self._px(5), self._px(6))
        )

        # -------------------------------------------------------------
        # URLs + panel lateral
        # -------------------------------------------------------------
        middle = tk.Frame(root, bg=self.BG, height=self._px(215))
        middle.grid(row=3, column=0, sticky="ew")
        middle.grid_propagate(False)
        middle.grid_columnconfigure(0, weight=5)
        middle.grid_columnconfigure(1, weight=2)
        middle.grid_rowconfigure(0, weight=1)

        url_card = tk.Frame(
            middle,
            bg=self.WHITE,
            highlightbackground=self.BORDER,
            highlightthickness=self._px(1),
        )
        url_card.grid(row=0, column=0, sticky="nsew", padx=(0, self._px(10)))
        url_card.grid_columnconfigure(0, weight=1)
        url_card.grid_rowconfigure(2, weight=1)

        tk.Label(
            url_card,
            text="URLs detectadas del módulo",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 12, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=self._px(12),
            pady=(self._px(6), self._px(2)),
        )

        tk.Label(
            url_card,
            text="Se autocompletan al buscar el módulo. Podés revisarlas mientras avanza la descarga.",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=self._px(12),
            pady=(0, self._px(4)),
        )

        text_frame = tk.Frame(url_card, bg=self.WHITE)
        text_frame.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=self._px(12),
            pady=(0, self._px(4)),
        )
        text_frame.grid_columnconfigure(0, weight=1)
        text_frame.grid_rowconfigure(0, weight=1)

        self.urls_text = tk.Text(
            text_frame,
            wrap="none",
            font=("Consolas", 10),
            bg=self.WHITE,
            fg=self.TEXT,
            relief="solid",
            bd=1,
            height=4,
            padx=self._px(6),
            pady=self._px(4),
        )
        self.urls_text.grid(row=0, column=0, sticky="nsew")

        url_scroll = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=self.urls_text.yview,
        )
        url_scroll.grid(row=0, column=1, sticky="ns")
        self.urls_text.configure(yscrollcommand=url_scroll.set)

        tk.Label(
            url_card,
            text="ⓘ Las evaluaciones y quizzes se detectan y se omiten automáticamente.",
            bg=self.WHITE,
            fg="#4b5563",
            font=("Segoe UI", 9),
        ).grid(
            row=3,
            column=0,
            sticky="e",
            padx=self._px(12),
            pady=(0, self._px(4)),
        )

        # Panel lateral
        helper = tk.Frame(
            middle,
            bg=self.WHITE,
            highlightbackground=self.BORDER,
            highlightthickness=self._px(1),
            padx=self._px(12),
            pady=self._px(7),
        )
        helper.grid(row=0, column=1, sticky="nsew")

        tk.Label(
            helper,
            text="¿Qué detecta el extractor?",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, self._px(5)))

        self._helper_item(
            helper,
            "PDF",
            self.RED,
            "PDF → descarga o reconstrucción\ncomo documento .pdf",
        )
        self._helper_item(
            helper,
            "≡",
            "#1f6fd6",
            "Página Canvas (texto e imágenes) →\nse convierte en .pdf",
        )
        self._helper_item(
            helper,
            "▶",
            self.PURPLE,
            "Video → MP4 con subtítulos\nincrustados y archivo .txt",
        )

        # -------------------------------------------------------------
        # Botones de Acción
        # -------------------------------------------------------------
        buttons = tk.Frame(root, bg=self.BG)
        buttons.grid(row=4, column=0, sticky="ew", pady=(self._px(6), self._px(4)))
        buttons.grid_columnconfigure(3, weight=1)

        self.login_btn = tk.Button(
            buttons,
            text="🌐  1. Iniciar sesión AWS",
            command=self._login,
            bg=self.BLUE,
            fg="white",
            activebackground=self.BLUE_ACTIVE,
            activeforeground="white",
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 11),
            padx=self._px(12),
            pady=self._px(4),
        )
        self.login_btn.grid(row=0, column=0, sticky="w")

        self.download_btn = tk.Button(
            buttons,
            text="⇩  2. Descargar módulo",
            command=self._download,
            bg=self.GREEN,
            fg="white",
            activebackground=self.GREEN_ACTIVE,
            activeforeground="white",
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 11),
            padx=self._px(20),
            pady=self._px(4),
        )
        self.download_btn.grid(row=0, column=1, sticky="w", padx=(self._px(10), 0))

        self.cancel_btn = tk.Button(
            buttons,
            text="⏹  Detener",
            command=self._cancel,
            bg=self.RED,
            fg="white",
            activebackground=self.RED_ACTIVE,
            activeforeground="white",
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 11),
            state="disabled",
            padx=self._px(12),
            pady=self._px(4),
        )
        self.cancel_btn.grid(row=0, column=2, sticky="w", padx=(self._px(10), 0))

        right_buttons = tk.Frame(buttons, bg=self.BG)
        right_buttons.grid(row=0, column=4, sticky="e")

        ttk.Button(
            right_buttons,
            text="📁  Abrir carpeta",
            command=self._open_module_folder,
        ).pack(side="left", padx=(0, self._px(6)))

        ttk.Button(
            right_buttons,
            text="🧹  Limpiar",
            command=self._clear_urls,
        ).pack(side="left")

        # -------------------------------------------------------------
        # Barra de progreso
        # -------------------------------------------------------------
        progress_row = tk.Frame(root, bg=self.BG)
        progress_row.grid(row=5, column=0, sticky="ew", pady=(0, self._px(5)))
        progress_row.grid_columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar(value=0)

        self.progress = ttk.Progressbar(
            progress_row,
            maximum=100,
            variable=self.progress_var,
            style="Green.Horizontal.TProgressbar",
        )
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, self._px(10)))

        self.progress_label = tk.Label(
            progress_row,
            text="0%",
            bg=self.BG,
            fg="#0f69c9",
            font=("Segoe UI", 10, "bold"),
            width=8,
            anchor="e",
        )
        self.progress_label.grid(row=0, column=1, sticky="e")

        # -------------------------------------------------------------
        # Log
        # -------------------------------------------------------------
        log_card = tk.Frame(
            root,
            bg=self.WHITE,
            highlightbackground=self.BORDER,
            highlightthickness=self._px(1),
        )
        log_card.grid(row=6, column=0, sticky="nsew", pady=(0, self._px(4)))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        tk.Label(
            log_card,
            text="Registro de ejecución (Log)",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=self._px(12),
            pady=(self._px(6), self._px(2)),
        )

        log_frame = tk.Frame(log_card, bg=self.WHITE)
        log_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=self._px(12),
            pady=(0, self._px(6)),
        )
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_widget = tk.Text(
            log_frame,
            wrap="word",
            bg=self.WHITE,
            fg=self.TEXT,
            relief="flat",
            bd=0,
            font=("Consolas", 10),
            state="disabled",
            padx=0,
            pady=0,
        )
        self.log_widget.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_widget.yview,
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=log_scroll.set)

        if self.settings.env_path.exists():
            self._append_log_line(f".env cargado: {self.settings.env_path}")
        else:
            self._append_log_line(f"AVISO: no se encontró archivo .env en: {self.settings.env_path}")

        self._append_log_line(f"Carpeta de salida: {self.output_var.get()}")
        self._append_log_line(
            "Reanudación: ACTIVA. Archivos ya descargados y válidos serán omitidos."
        )

    def _helper_item(self, parent, icon_text, icon_bg, text):
        row = tk.Frame(parent, bg=self.WHITE)
        row.pack(fill="x", anchor="w", pady=self._px(3))

        icon_size = self._px(26)
        icon_holder = tk.Frame(row, bg=icon_bg, width=icon_size, height=icon_size)
        icon_holder.pack_propagate(False)
        icon_holder.pack(side="left", anchor="n", padx=(0, self._px(8)))

        tk.Label(
            icon_holder,
            text=icon_text,
            bg=icon_bg,
            fg="white",
            font=("Segoe UI", 9, "bold"),
        ).pack(expand=True, fill="both")

        tk.Label(
            row,
            text=text,
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

    def _choose_output(self):
        folder = filedialog.askdirectory(
            initialdir=(self.output_var.get() or str(Path.home()))
        )
        if folder:
            self.output_var.set(folder)

    def _login(self):
        if self.login_in_progress:
            self._confirm_login()
            return

        self.login_in_progress = True
        self.login_done_event.clear()

        self.login_btn.config(text="✓  Guardar sesión")
        self.download_btn.config(state="disabled")
        self.list_modules_btn.config(state="disabled")

        def task():
            try:
                self.extractor.open_login(
                    self.home_var.get().strip(),
                    self.login_done_event,
                )
            except Exception as exc:
                self._thread_error(str(exc))
            finally:
                self.login_in_progress = False
                self.after(0, self._login_finished)

        threading.Thread(target=task, daemon=True).start()

    def _confirm_login(self):
        self.login_btn.config(state="disabled")
        self._append_log_line("Guardando sesión del navegador...")
        self.login_done_event.set()

    def _login_finished(self):
        self.login_btn.config(
            text="🌐  1. Iniciar sesión AWS",
            state="normal",
        )
        self.download_btn.config(state="normal")
        self.list_modules_btn.config(state="normal")

    def _list_modules(self):
        home_url = self.home_var.get().strip()
        if not home_url:
            messagebox.showwarning(APP_NAME, "Configurá la URL de AWS Academy en .env")
            return

        self.list_modules_btn.config(state="disabled")
        self._append_log_line("Listando módulos del curso...")

        def task():
            try:
                modules = self.extractor.list_course_modules(home_url)
                if modules:
                    def update_combo():
                        self.module_combo["values"] = modules
                        if not self.module_var.get() and modules:
                            self.module_combo.current(0)
                        self._append_log_line(f"Se cargaron {len(modules)} módulos en el desplegable.")
                    self.after(0, update_combo)
                else:
                    self._append_log_line("No se encontraron módulos.")
            except Exception as exc:
                self._thread_error(f"Error listando módulos: {exc}")
            finally:
                self.after(0, lambda: self.list_modules_btn.config(state="normal"))

        threading.Thread(target=task, daemon=True).start()

    def _cancel(self):
        if self.download_in_progress:
            self._append_log_line("Cancelación solicitada por el usuario...")
            self.cancel_event.set()
            self.cancel_btn.config(state="disabled")

    def _show_discovered_items(self, discovery: dict):
        downloadables = discovery.get("downloadables") or []
        skipped = discovery.get("skipped") or []

        self.urls_text.config(state="normal")
        self.urls_text.delete("1.0", "end")

        for item in downloadables:
            url = str(item.get("href") or "").strip()
            if url:
                self.urls_text.insert("end", url + "\n")

        self.urls_text.see("1.0")
        self._append_log_line(
            f"Vista previa: {len(downloadables)} descargables, {len(skipped)} omitidos."
        )

    def _download(self):
        module = self.module_var.get().strip()
        output = self.output_var.get().strip()
        home_url = self.home_var.get().strip()

        if not module:
            messagebox.showwarning(
                APP_NAME,
                "Escribí o seleccioná el título del módulo a descargar.",
            )
            return

        if not output:
            messagebox.showwarning(APP_NAME, "Indicá la carpeta de salida.")
            return

        if not home_url:
            messagebox.showwarning(APP_NAME, "URL base de AWS Academy no configurada.")
            return

        self.download_in_progress = True
        self.cancel_event.clear()

        self.login_btn.config(state="disabled")
        self.download_btn.config(state="disabled")
        self.list_modules_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._set_progress(0)

        self.urls_text.config(state="normal")
        self.urls_text.delete("1.0", "end")
        self._append_log_line(f'Buscando y procesando módulo: "{module}"')

        def task():
            try:
                def on_discovery(disc):
                    self.after(0, lambda d=disc: self._show_discovered_items(d))

                module_dir, results, errors = self.extractor.download_batch(
                    items=None,
                    module=module,
                    output_root=output,
                    home_url=home_url,
                    discovery_callback=on_discovery,
                    cancel_event=self.cancel_event,
                )

                if self.cancel_event.is_set():
                    self._append_log_line("Descarga interrumpida.")
                    self.after(0, self._enable_buttons)
                    return

                drive_result = self.drive_uploader.upload_results(
                    module_name=module_dir.name,
                    local_paths=results,
                )

                def finished():
                    self._enable_buttons()

                    lines = [f"{len(results)} archivo(s) guardados en:\n{module_dir}"]

                    if drive_result.get("enabled"):
                        lines.append("")
                        if drive_result.get("ok"):
                            lines.append(
                                f"Google Drive: OK\n{drive_result.get('remote_folder_name', '')}\n"
                                f"Nuevos: {drive_result.get('uploaded', 0)} | "
                                f"Actualizados: {drive_result.get('updated', 0)}"
                            )
                        elif drive_result.get("skipped"):
                            lines.append(f"Google Drive: omitido ({drive_result.get('message', '')})")
                        else:
                            lines.append(f"Google Drive: ERROR ({drive_result.get('message', '')})")

                    if errors:
                        detail = "\n".join(f"- {name}: {err}" for name, err in errors)
                        lines.extend(["", f"Errores de extracción: {len(errors)}", detail])

                    message = "\n".join(lines)
                    drive_failed = (
                        drive_result.get("enabled")
                        and drive_result.get("attempted")
                        and not drive_result.get("ok")
                    )

                    if errors or drive_failed:
                        messagebox.showwarning(APP_NAME, message)
                    else:
                        messagebox.showinfo(APP_NAME, "Proceso completado.\n\n" + message)

                self.after(0, finished)

            except Exception as exc:
                self._thread_error(str(exc))
                self.after(0, self._enable_buttons)
            finally:
                self.download_in_progress = False

        threading.Thread(target=task, daemon=True).start()

    def _enable_buttons(self):
        self.download_in_progress = False
        self.login_btn.config(text="🌐  1. Iniciar sesión AWS", state="normal")
        self.download_btn.config(state="normal")
        self.list_modules_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

    def _clear_urls(self):
        self.urls_text.delete("1.0", "end")
        self._set_progress(0)

    def _open_module_folder(self):
        root = Path(self.output_var.get()).expanduser()
        module = safe_name(self.module_var.get(), "Sin_modulo")
        path = root / module
        path.mkdir(parents=True, exist_ok=True)

        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    def _thread_log(self, text: str):
        self.after(0, lambda: self._append_log_line(text))

    def _thread_progress(self, value: int):
        self.after(0, lambda: self._set_progress(value))

    def _thread_sub_progress(self, value: int):
        self.after(0, lambda: self._set_sub_progress(value))

    def _thread_error(self, text: str):
        self.after(0, lambda: self._append_log_line("ERROR: " + text))
        self.after(0, lambda: messagebox.showerror(APP_NAME, text))

    def _set_progress(self, value: int):
        value = max(0, min(100, int(value)))
        self.progress_var.set(value)
        self.progress_label.config(text=f"{value}%")

    def _set_sub_progress(self, value: int):
        value = max(0, min(100, int(value)))
        self.progress_label.config(text=f"FFmpeg {value}%")

    def _append_log_line(self, text: str, max_lines: int = 2500):
        timestamp = time.strftime("%H:%M:%S")
        self.log_widget.config(state="normal")

        for line in str(text).splitlines() or [""]:
            self.log_widget.insert("end", f"[{timestamp}] {line}\n")

        try:
            num_lines = int(self.log_widget.index("end-1c").split(".")[0])
            if num_lines > max_lines:
                self.log_widget.delete("1.0", f"{num_lines - max_lines}.0")
        except Exception:
            pass

        self.log_widget.see("end")
        self.log_widget.config(state="disabled")


def launch():
    enable_windows_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    launch()

