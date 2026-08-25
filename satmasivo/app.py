"""Ventana principal: tkinter (Linux y Windows)."""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import date, datetime
from calendar import monthrange
from io import BytesIO
from pathlib import Path
import uuid as uuidlib
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from satmasivo import __version__
from satmasivo.cfdi import scan_folder
from satmasivo.ciec_login import CiecClient
from satmasivo.config import load_config, save_config
from satmasivo.excel import export_excel
from satmasivo.fiel import load_fiel
from satmasivo.pdf import cfdi_to_pdf
from satmasivo.portal import descargar_con_sesion
from satmasivo.sat_ws import SatError, SatMasiva, extraer_zip
from satmasivo.update import apply_update, check_latest, save_token
from satmasivo.validar import validar_rows

BLUE = "#0078D4"


def _png_bytes(data: bytes) -> bytes:
    """JPEG/GIF/etc → PNG. El SAT manda JPEG; tk.PhotoImage no lee JPEG."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    from PIL import Image

    im = Image.open(BytesIO(data))
    if im.mode not in {"RGB", "RGBA", "L", "P"}:
        im = im.convert("RGB")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _photo_from_bytes(data: bytes) -> tk.PhotoImage:
    """Pinta el captcha sin python3-pil.imagetk (ImageTk no viene en python3-pil)."""
    return tk.PhotoImage(data=_png_bytes(data))


MESES = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


def pick_date(parent, var: tk.StringVar) -> None:
    try:
        cur = datetime.strptime(var.get().strip(), "%Y-%m-%d").date()
    except ValueError:
        cur = date.today()
    pop = tk.Toplevel(parent)
    pop.title("Fecha")
    pop.transient(parent)
    pop.resizable(False, False)
    state = {"y": cur.year, "m": cur.month}
    head = tk.Frame(pop)
    head.pack(fill=tk.X, padx=6, pady=4)
    title = tk.Label(head, font=("Segoe UI", 10, "bold"))
    title.pack(side=tk.LEFT, expand=True)
    gridf = tk.Frame(pop)
    gridf.pack(padx=6, pady=4)

    def paint() -> None:
        for w in gridf.winfo_children():
            w.destroy()
        title.configure(text=f"{MESES[state['m'] - 1]} {state['y']}")
        for i, dname in enumerate(("Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do")):
            tk.Label(gridf, text=dname, width=3, fg="#555").grid(row=0, column=i)
        first = date(state["y"], state["m"], 1).weekday()
        days = monthrange(state["y"], state["m"])[1]
        r = 1
        c = first
        for day in range(1, days + 1):
            d = day

            def choose(dd=d, yy=state["y"], mm=state["m"]):
                var.set(f"{yy:04d}-{mm:02d}-{dd:02d}")
                pop.destroy()

            tk.Button(gridf, text=str(d), width=3, command=choose).grid(row=r, column=c)
            c += 1
            if c > 6:
                c = 0
                r += 1

    def prev() -> None:
        if state["m"] == 1:
            state["m"] = 12
            state["y"] -= 1
        else:
            state["m"] -= 1
        paint()

    def nxt() -> None:
        if state["m"] == 12:
            state["m"] = 1
            state["y"] += 1
        else:
            state["m"] += 1
        paint()

    ttk.Button(head, text="<", width=3, command=prev).pack(side=tk.LEFT)
    ttk.Button(head, text=">", width=3, command=nxt).pack(side=tk.RIGHT)
    paint()
    pop.grab_set()


class SatMasivoApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SAT Masivo {__version__}")
        self.geometry("1040x700")
        self.minsize(900, 600)
        self.sentido = "recibidas"
        self._busy = False
        self._download_dir = Path.home() / "satmasivo"
        self._download_dir.mkdir(exist_ok=True)
        prev = str(load_config().get("last_sesion") or load_config().get("last_lote") or "")
        self._last_lote = Path(prev) if prev else None
        self._session_dir: Path | None = None
        self.ciec = CiecClient()
        self._logged_rfc = ""
        self._login_busy = False
        self._captcha_photo = None
        self._build()
        self._mark("home")
        self.after(200, self._reload_captcha)
        self.after(8000, self._silent_update_check)

    def _build(self) -> None:
        bar = tk.Frame(self, bg=BLUE, padx=8, pady=8)
        bar.pack(fill=tk.X)
        nav = tk.Frame(bar, bg=BLUE)
        nav.pack(side=tk.LEFT)
        self.btn_home = self._tool(nav, "Home", self.go_home)
        self.btn_rec = self._tool(nav, "Recibidas", lambda: self.set_sentido("recibidas"))
        self.btn_emi = self._tool(nav, "Emitidas", lambda: self.set_sentido("emitidas"))
        acts = tk.Frame(bar, bg=BLUE)
        acts.pack(side=tk.LEFT, padx=12)
        self._tool(acts, "Descargar", self.on_descargar)
        self._tool(acts, "Reporte", self.on_reporte_actual)
        self._tool(acts, "XML a PDF", self.on_xml_pdf)
        self._tool(acts, "Reporte CFDi\nde una carpeta", self.on_reporte_carpeta)
        self._tool(acts, "Actualizar", self.on_actualizar)
        hint = tk.Label(
            bar,
            text="Home = RFC + CIEC + captcha.\nLuego Recibidas/Emitidas y Descargar.",
            bg=BLUE,
            fg="white",
            font=("Segoe UI", 10, "bold"),
            justify=tk.LEFT,
        )
        hint.pack(side=tk.RIGHT, padx=8)

        self.pages = ttk.Notebook(self)
        self.pages.pack(fill=tk.BOTH, expand=True)
        self.page_home = tk.Frame(self.pages, bg="white")
        self.page_work = tk.Frame(self.pages, bg="white")
        self.pages.add(self.page_home, text="Home")
        self.pages.add(self.page_work, text="Lote")
        self._hide_tabs()
        self._build_login(self.page_home)
        self._build_work(self.page_work)

        self.status = tk.StringVar(value="Home — login SAT")
        tk.Label(self, textvariable=self.status, anchor="w", bg="#f3f3f3").pack(fill=tk.X, side=tk.BOTTOM)

    def _build_work(self, parent: tk.Widget) -> None:
        self.lbl_work = tk.Label(
            parent,
            text="",
            bg="white",
            fg="#0b3d61",
            font=("Segoe UI", 14),
            justify=tk.CENTER,
        )
        self.lbl_work.pack(fill=tk.X, pady=(16, 4))
        self.var_prog = tk.StringVar(value="")
        tk.Label(parent, textvariable=self.var_prog, bg="white", fg="#333", font=("Segoe UI", 10)).pack()
        self.bar = ttk.Progressbar(parent, maximum=100, mode="determinate")
        self.bar.pack(fill=tk.X, padx=24, pady=8)
        box = tk.Frame(parent, bg="white")
        box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        scroll = ttk.Scrollbar(box)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lst_prog = tk.Listbox(box, font=("Consolas", 9), yscrollcommand=scroll.set, activestyle="none")
        self.lst_prog.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.configure(command=self.lst_prog.yview)

    def _hide_tabs(self) -> None:
        try:
            self.pages.hide(self.page_work)
        except tk.TclError:
            pass

    def _tool(self, parent: tk.Widget, caption: str, cmd) -> tk.Button:
        b = tk.Button(
            parent,
            text=caption,
            command=cmd,
            width=14,
            height=3,
            bg="white",
            fg="#0b3d61",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
        )
        b.pack(side=tk.LEFT, padx=4)
        return b

    def _build_login(self, parent: tk.Widget) -> None:
        box = tk.Frame(parent, bg="white")
        box.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(box, text="Acceso por contraseña", bg="white", fg="#0b3d61", font=("Segoe UI", 18, "bold")).pack(pady=(0, 6))
        tk.Label(
            box,
            text="Misma CIEC del SAT. El captcha lo resuelves tú.\nNo guardamos la contraseña.",
            bg="white",
            justify=tk.CENTER,
        ).pack(pady=(0, 12))
        grid = tk.Frame(box, bg="white")
        grid.pack()
        self.ent_rfc = ttk.Entry(grid, width=32)
        self.ent_pwd = ttk.Entry(grid, width=32, show="*")
        self.ent_cap = ttk.Entry(grid, width=32)
        self.ent_rfc.insert(0, "")
        tk.Label(grid, text="RFC", bg="white").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        self.ent_rfc.grid(row=0, column=1, pady=4)
        tk.Label(grid, text="Contraseña", bg="white").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.ent_pwd.grid(row=1, column=1, pady=4)
        tk.Label(grid, text="Captcha", bg="white").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        capf = tk.Frame(grid, bg="white")
        capf.grid(row=2, column=1, sticky="w")
        self.img_cap = tk.Label(capf, bg="#eef3f8", width=24, height=4)
        self.img_cap.pack(side=tk.LEFT)
        ttk.Button(capf, text="Otro captcha", command=self._reload_captcha).pack(side=tk.LEFT, padx=8)
        self.ent_cap.grid(row=3, column=1, pady=4)
        ttk.Button(grid, text="Enviar", command=self.on_login).grid(row=4, column=1, sticky="w", pady=10)
        self.lbl_login = tk.Label(grid, text="", bg="white", fg="#a33", wraplength=360, justify=tk.LEFT)
        self.lbl_login.grid(row=5, column=1, sticky="w")
        self.ent_cap.bind("<Return>", lambda *_: self.on_login())

    def _mark(self, which: str) -> None:
        mapping = {"home": self.btn_home, "recibidas": self.btn_rec, "emitidas": self.btn_emi}
        for b in mapping.values():
            b.configure(bg="white")
        mapping[which].configure(bg="#fff3c4")

    def go_home(self) -> None:
        self._mark("home")
        self.pages.select(self.page_home)
        self.status.set("Home — login SAT")

    def set_sentido(self, sentido: str) -> None:
        self.sentido = sentido
        self._mark(sentido)
        if not self._logged_rfc:
            self.go_home()
            self.lbl_login.configure(text="Entra en Home primero (RFC + contraseña + captcha).")
            return
        self.pages.select(self.page_work)
        self.lbl_work.configure(text=f"Sesión {self._logged_rfc}\nModo {sentido}.\nPulsa Descargar.")
        self.status.set(f"Modo {sentido} · {self._logged_rfc}")

    def _ui(self, fn, *args) -> None:
        self.after(0, lambda: fn(*args))

    def _reset_prog(self, title: str) -> None:
        try:
            self.pages.tab(self.page_work, state="normal")
        except tk.TclError:
            try:
                self.pages.add(self.page_work, text="Lote")
            except tk.TclError:
                pass
        try:
            self.pages.select(self.page_work)
        except tk.TclError:
            pass
        self.lbl_work.configure(text=title)
        self.var_prog.set("0%")
        self.bar.configure(mode="determinate", maximum=100, value=0)
        self.lst_prog.delete(0, tk.END)

    def _prog(self, ev: dict) -> None:
        msg = str(ev.get("msg") or "")
        done = int(ev.get("done") or 0)
        total = int(ev.get("total") or 0)
        if total > 0:
            pct = min(100, int(100 * done / total))
            self.bar.configure(mode="determinate", maximum=total, value=done)
            self.var_prog.set(f"{pct}%   {msg}")
        else:
            self.var_prog.set(msg)
        uid = str(ev.get("uuid") or "")
        if uid or ev.get("phase") in {"xml", "validar"}:
            mark = "OK" if ev.get("ok", True) else "--"
            line = f"{mark}  {uid}  {msg}".strip()
            self.lst_prog.insert(tk.END, line)
            if self.lst_prog.size() > 800:
                self.lst_prog.delete(0, 200)
            self.lst_prog.see(tk.END)
        self.status.set(msg or self.var_prog.get())

    def _on_progress(self, ev: dict) -> None:
        self._ui(self._prog, dict(ev))

    def _reload_captcha(self) -> None:
        if self._login_busy:
            return
        self.lbl_login.configure(text="Cargando captcha del SAT…")

        def work():
            try:
                img = self.ciec.start()
                self._ui(self._show_captcha, img, "")
            except Exception as exc:
                self._ui(self._show_captcha, b"", str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _show_captcha(self, data: bytes, err: str, keep: str = "") -> None:
        if err:
            self.lbl_login.configure(text=err)
            return
        try:
            photo = _photo_from_bytes(data)
            self._captcha_photo = photo
            self.img_cap.configure(image=photo, width=photo.width(), height=photo.height())
            self.lbl_login.configure(text=keep)
        except Exception as exc:
            self.lbl_login.configure(text=keep or f"No se pudo pintar el captcha: {exc}")

    def on_login(self) -> None:
        rfc = self.ent_rfc.get().strip()
        pwd = self.ent_pwd.get()
        cap = self.ent_cap.get().strip()
        if not rfc or not pwd or not cap:
            self.lbl_login.configure(text="Llena RFC, contraseña y captcha.")
            return
        if getattr(self, "_login_busy", False):
            self.lbl_login.configure(text="Ya se está intentando entrar.")
            return
        self._login_busy = True
        self.lbl_login.configure(text="Entrando al SAT…")
        done = {"ok": False}

        def work():
            try:
                got = self.ciec.login(rfc, pwd, cap)
                done["ok"] = True
                self._ui(self._login_ok, got)
            except Exception as exc:
                done["ok"] = True
                self._ui(self._login_fail, str(exc))

        def watchdog():
            if not done["ok"]:
                self._login_busy = False
                self.lbl_login.configure(
                    text="El SAT no respondió a tiempo. Pulsa Enviar otra vez."
                )

        threading.Thread(target=work, daemon=True).start()
        self.after(45000, watchdog)

    def _login_ok(self, rfc: str) -> None:
        self._login_busy = False
        self._logged_rfc = rfc
        self._session_dir = None
        self.ent_pwd.delete(0, tk.END)
        self.ent_cap.delete(0, tk.END)
        self.lbl_login.configure(text=f"Sesión {rfc}")
        self.set_sentido(self.sentido)
        messagebox.showinfo("Sesión SAT", f"Entraste como {rfc}. Ya puedes Descargar.")

    def _login_fail(self, msg: str) -> None:
        self._login_busy = False
        self.ent_cap.delete(0, tk.END)
        if self.ciec.captcha:
            self._show_captcha(self.ciec.captcha, "", keep=msg)
        else:
            self.lbl_login.configure(text=msg)
        messagebox.showerror("Login SAT", msg)

    def _remember_sesion(self, dest: Path) -> None:
        self._session_dir = dest
        self._last_lote = dest
        cfg = load_config()
        cfg["last_sesion"] = str(dest)
        cfg["last_lote"] = str(dest)
        save_config(cfg)

    def _ensure_session_dir(self, dest_base: str, rfc: str) -> Path:
        if self._session_dir and self._session_dir.is_dir():
            return self._session_dir
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuidlib.uuid4().hex[:6]
        root = Path(dest_base) / "sesion-sat" / (rfc or "sin-rfc") / stamp
        root.mkdir(parents=True, exist_ok=True)
        self._remember_sesion(root)
        return root

    def on_reporte_carpeta(self) -> None:
        folder = filedialog.askdirectory(title="Carpeta con XML")
        if not folder:
            return
        dest = filedialog.asksaveasfilename(
            title="Guardar Excel",
            defaultextension=".xlsx",
            initialdir=str(Path.home()),
            initialfile="reporte-cfdi.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not dest:
            return
        self._run_bg("Generando reporte…", lambda: self._job_reporte(folder, dest, True))

    def on_reporte_actual(self) -> None:
        ses = self._session_dir
        if ses is None or not Path(ses).is_dir() or not any(Path(ses).rglob("*.xml")):
            messagebox.showerror(
                "Reporte",
                "No hay XML en esta sesión. Primero Descargar (recibidas y/o emitidas).",
            )
            return
        dest = filedialog.asksaveasfilename(
            title="Guardar reporte de la sesión",
            defaultextension=".xlsx",
            initialdir=str(Path.home()),
            initialfile="reporte.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not dest:
            return
        self._run_bg("Generando reporte de la sesión…", lambda: self._job_reporte(str(ses), dest, True))

    def on_xml_pdf(self) -> None:
        xml = filedialog.askopenfilename(title="CFDI XML", filetypes=[("XML", "*.xml")])
        if not xml:
            return
        dest = filedialog.asksaveasfilename(
            title="Guardar PDF",
            defaultextension=".pdf",
            initialfile=Path(xml).with_suffix(".pdf").name,
            filetypes=[("PDF", "*.pdf")],
        )
        if not dest:
            return
        try:
            cfdi_to_pdf(xml, dest)
            messagebox.showinfo("PDF listo", dest)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_descargar(self) -> None:
        win = tk.Toplevel(self)
        win.title("Descargar del SAT")
        win.geometry("520x420")
        win.transient(self)
        modo = tk.StringVar(value="ciec")
        ttk.Radiobutton(win, text="Sesión SAT (la de Home)", variable=modo, value="ciec").pack(anchor="w", padx=12, pady=4)
        ttk.Radiobutton(win, text="e.firma (.cer + .key) — Web Service", variable=modo, value="fiel").pack(anchor="w", padx=12, pady=4)
        grid = tk.Frame(win)
        grid.pack(fill=tk.X, padx=12, pady=8)
        cer = tk.StringVar()
        key = tk.StringVar()
        pwd = tk.StringVar()
        ini = tk.StringVar(value=datetime.now().replace(day=1).strftime("%Y-%m-%d"))
        fin = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        tipo = tk.StringVar(value="CFDI")
        estado = tk.StringVar(value="Todos")
        dest = tk.StringVar(value=str(self._download_dir))
        validar = tk.BooleanVar(value=True)

        def row(r: int, label: str, widget) -> None:
            tk.Label(grid, text=label).grid(row=r, column=0, sticky="e", padx=4, pady=3)
            widget.grid(row=r, column=1, sticky="ew", pady=3)

        grid.columnconfigure(1, weight=1)
        e_cer = ttk.Entry(grid, textvariable=cer, width=36)
        e_key = ttk.Entry(grid, textvariable=key, width=36)
        e_pwd = ttk.Entry(grid, textvariable=pwd, show="*")
        row(0, ".cer", e_cer)
        ttk.Button(grid, text="…", width=3, command=lambda: cer.set(filedialog.askopenfilename(filetypes=[("CER", "*.cer")]) or cer.get())).grid(row=0, column=2)
        row(1, ".key", e_key)
        ttk.Button(grid, text="…", width=3, command=lambda: key.set(filedialog.askopenfilename(filetypes=[("KEY", "*.key")]) or key.get())).grid(row=1, column=2)
        row(2, "Contraseña FIEL", e_pwd)
        e_ini = ttk.Entry(grid, textvariable=ini)
        e_fin = ttk.Entry(grid, textvariable=fin)
        row(3, "Fecha inicial", e_ini)
        ttk.Button(grid, text="…", width=3, command=lambda: pick_date(win, ini)).grid(row=3, column=2)
        row(4, "Fecha final", e_fin)
        ttk.Button(grid, text="…", width=3, command=lambda: pick_date(win, fin)).grid(row=4, column=2)
        e_ini.bind("<Button-1>", lambda *_: pick_date(win, ini))
        e_fin.bind("<Button-1>", lambda *_: pick_date(win, fin))
        cb_tipo = ttk.Combobox(grid, textvariable=tipo, values=("CFDI", "Metadata"), state="readonly")
        cb_est = ttk.Combobox(grid, textvariable=estado, values=("Todos", "Vigente", "Cancelado"), state="readonly")
        row(5, "Tipo (e.firma)", cb_tipo)
        row(6, "Estado (e.firma)", cb_est)
        row(7, "Destino", ttk.Entry(grid, textvariable=dest))
        ttk.Button(grid, text="…", width=3, command=lambda: dest.set(filedialog.askdirectory() or dest.get())).grid(row=7, column=2)
        ttk.Checkbutton(win, text="Validar vigencia en el SAT al terminar", variable=validar).pack(anchor="w", padx=12)

        def toggle(*_):
            use = modo.get() == "fiel"
            for w in (e_cer, e_key, e_pwd, cb_tipo, cb_est):
                w.configure(state=tk.NORMAL if use else tk.DISABLED)

        modo.trace_add("write", toggle)
        toggle()

        def ok():
            args = {
                "modo": modo.get(),
                "cer": cer.get(),
                "key": key.get(),
                "pwd": pwd.get(),
                "ini": ini.get().strip(),
                "fin": fin.get().strip(),
                "tipo": tipo.get(),
                "estado": estado.get(),
                "dest": dest.get(),
                "validar": validar.get(),
                "sentido": self.sentido,
            }
            win.destroy()
            if not args["dest"]:
                messagebox.showerror("Error", "Falta carpeta destino.")
                return
            self._download_dir = Path(args["dest"])
            if args["modo"] == "fiel":
                if not args["cer"] or not args["key"] or not args["pwd"]:
                    messagebox.showerror("Error", "Para e.firma hacen falta .cer, .key y contraseña.")
                    return
                self._reset_prog(f"e.firma · {args['sentido']}")
                self._run_bg("Descargando por e.firma…", lambda: self._job_descarga_fiel(args))
                return
            if not self._logged_rfc:
                messagebox.showerror("Error", "Entra en Home primero.")
                return
            self._reset_prog(f"Sesión {self._logged_rfc} · {args['sentido']}")
            self._run_bg("Descargando con sesión SAT…", lambda: self._job_descarga_ciec(args))

        ttk.Button(win, text="Descargar", command=ok).pack(pady=10)

    def on_actualizar(self) -> None:
        self._run_bg("Buscando actualización…", self._job_check_update)

    def _silent_update_check(self) -> None:
        def work():
            try:
                rel = check_latest()
            except Exception:
                return
            if rel:
                self._ui(self.status.set, f"Hay {rel.tag} disponible. Pulsa Actualizar.")

        threading.Thread(target=work, daemon=True).start()

    def _ask_token(self) -> str | None:
        win = tk.Toplevel(self)
        win.title("Token de GitHub")
        tk.Label(win, text="Repo privado. Token con lectura de releases, o gh auth login.").pack(padx=10, pady=8)
        var = tk.StringVar()
        ttk.Entry(win, textvariable=var, show="*", width=48).pack(padx=10)
        out = {"v": None}

        def save():
            tok = var.get().strip()
            if tok:
                save_token(tok)
            out["v"] = tok or None
            win.destroy()

        ttk.Button(win, text="Guardar", command=save).pack(pady=8)
        win.transient(self)
        win.grab_set()
        self.wait_window(win)
        return out["v"]

    def _run_bg(self, status: str, fn) -> None:
        if self._busy:
            messagebox.showerror("Error", "Ya hay una operación en curso.")
            return
        self._busy = True
        self.status.set(status)

        def wrap():
            try:
                msg = fn()
                self._ui(self._done, True, msg)
            except SatError as exc:
                self._ui(self._done, False, str(exc))
            except Exception as exc:
                self._ui(self._done, False, f"{exc}\n\n{traceback.format_exc()}")

        threading.Thread(target=wrap, daemon=True).start()

    def _done(self, ok: bool, msg: str) -> None:
        self._busy = False
        self.status.set("Listo" if ok else "Error")
        if msg == "__RESTART__":
            self.destroy()
            return
        if msg == "__NEED_TOKEN__":
            if self._ask_token():
                self._run_bg("Buscando actualización…", self._job_check_update)
            return
        if ok:
            messagebox.showinfo("Listo", msg)
        else:
            messagebox.showerror("Error", msg)

    def _job_reporte(self, folder: str, dest: str, validar: bool) -> str:
        rows = scan_folder(folder)
        if not rows:
            raise SatError(f"No hay XML de CFDI en {folder}")
        if validar:
            rows = validar_rows(rows)
        out = export_excel(rows, dest, rfc_firma=self._logged_rfc or None)
        return f"{len(rows)} comprobantes → {out}"

    def _job_descarga_fiel(self, args: dict) -> str:
        import time

        fiel = load_fiel(args["cer"], args["key"], args["pwd"])
        client = SatMasiva(fiel)
        ini = datetime.strptime(args["ini"], "%Y-%m-%d")
        fin = datetime.strptime(args["fin"], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        sol = client.solicitar(
            sentido=args["sentido"],
            fecha_inicial=ini,
            fecha_final=fin,
            tipo_solicitud=args["tipo"],
            estado_comprobante=args["estado"],
        )
        if not sol.id_solicitud:
            raise SatError(f"{sol.codigo} {sol.mensaje}".strip() or "Solicitud rechazada")
        dest = self._ensure_session_dir(args["dest"], fiel.rfc) / args["sentido"]
        dest.mkdir(parents=True, exist_ok=True)
        last = None
        for _ in range(90):
            last = client.verificar(sol.id_solicitud)
            self._ui(self.status.set, f"{last.estado_nombre} · {last.numero_cfdis} CFDI")
            self._on_progress(
                {
                    "phase": "consulta",
                    "done": min(_ + 1, 90),
                    "total": 90,
                    "msg": f"{last.estado_nombre} · {last.numero_cfdis} CFDI",
                }
            )
            if last.estado == 3:
                break
            if last.estado in {4, 5, 6}:
                raise SatError(f"{last.estado_nombre}: {last.mensaje}")
            time.sleep(20)
        else:
            raise SatError(f"Sigue en proceso. Id {sol.id_solicitud}.")
        for paq in last.paquetes:
            blob = client.descargar_paquete(paq)
            (dest / f"{paq}.zip").write_bytes(blob)
            extraer_zip(blob, str(dest))
        return self._finish_rows(dest, args["validar"], fiel.rfc, extra=f"Solicitud {sol.id_solicitud}\n")

    def _job_descarga_ciec(self, args: dict) -> str:
        dest = self._ensure_session_dir(args["dest"], self._logged_rfc) / args["sentido"]
        files = descargar_con_sesion(
            sess=self.ciec.sess,
            sentido=args["sentido"],
            dest=dest,
            fecha_ini=args["ini"],
            fecha_fin=args["fin"],
            progress=self._on_progress,
        )
        return self._finish_rows(
            dest, args["validar"], self._logged_rfc, extra=f"{len(files)} XML por sesión SAT\n"
        )

    def _finish_rows(self, dest: Path, validar: bool, rfc: str | None, extra: str = "") -> str:
        root = dest if dest.name not in {"recibidas", "emitidas"} else dest.parent
        self._remember_sesion(root)
        rows = scan_folder(root)
        if validar and rows:

            def on_val(i, total, uuid):
                self._on_progress(
                    {
                        "phase": "validar",
                        "done": i,
                        "total": total,
                        "uuid": uuid,
                        "ok": True,
                        "msg": f"Validando {i}/{total}",
                    }
                )

            rows = validar_rows(rows, progress=on_val)
        if rows:
            try:
                export_excel(rows, root / "reporte.xlsx", rfc_firma=rfc)
            except Exception as exc:
                return f"{extra}{len(rows)} XML. Excel no se pudo armar: {exc}\n{root}"
        return f"{extra}{len(rows)} comprobantes\n{root}"

    def _job_check_update(self) -> str:
        try:
            rel = check_latest()
        except PermissionError:
            return "__NEED_TOKEN__"
        if rel is None:
            return f"Ya estás en {__version__}."
        apply_update(rel)
        return "__RESTART__"


def main() -> None:
    try:
        app = SatMasivoApp()
        app.mainloop()
    except Exception as exc:
        sys.stderr.write(f"satmasivo: {exc}\n{traceback.format_exc()}")
        try:
            messagebox.showerror("SAT Masivo no pudo abrir", str(exc))
        except Exception:
            pass
        raise SystemExit(1)
