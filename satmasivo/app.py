"""Ventana principal: login SAT nativo + descarga."""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from satmasivo import __version__
from satmasivo.cfdi import scan_folder
from satmasivo.ciec_login import CiecClient
from satmasivo.excel import export_excel
from satmasivo.fiel import load_fiel
from satmasivo.pdf import cfdi_to_pdf
from satmasivo.portal import descargar_con_sesion
from satmasivo.sat_ws import SatError, SatMasiva, extraer_zip
from satmasivo.update import check_latest, download_deb, install_deb, save_token
from satmasivo.validar import validar_rows

BLUE = "#0078D4"

_CSS = f"""
window {{ background: #ffffff; }}
.toolbar {{ background: {BLUE}; padding: 6px 8px; }}
.toolbar button {{
    background: #ffffff;
    border: 1px solid #d0e6f8;
    border-radius: 6px;
    padding: 4px 8px;
    min-width: 86px;
    min-height: 64px;
}}
.toolbar button:hover {{ background: #e8f4ff; }}
.toolbar button.active {{
    background: #fff3c4;
    border-color: #f0c14b;
}}
.toolbar label {{ color: #0b3d61; font-weight: 600; }}
.hint {{ color: #ffffff; font-weight: 700; font-size: 13px; }}
.statusbar {{ background: #f3f3f3; padding: 2px 8px; font-size: 11px; }}
.login-title {{ font-size: 22px; font-weight: 700; color: #0b3d61; }}
""".encode()


def apply_css() -> Gtk.CssProvider:
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS)
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    return provider


def pixbuf_from_bytes(data: bytes) -> GdkPixbuf.Pixbuf | None:
    if not data:
        return None
    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        try:
            loader.close()
        except Exception:
            pass
        return None


class ToolButton(Gtk.Button):
    def __init__(self, icon_name: str, caption: str):
        super().__init__()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
        lab = Gtk.Label(label=caption)
        lab.set_justify(Gtk.Justification.CENTER)
        lab.set_line_wrap(True)
        lab.set_max_width_chars(12)
        box.pack_start(img, False, False, 0)
        box.pack_start(lab, False, False, 0)
        self.add(box)
        self.set_relief(Gtk.ReliefStyle.NONE)


class SatMasivoWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=f"SAT Masivo {__version__}")
        self.set_default_size(1100, 720)
        self.sentido = "recibidas"
        self._busy = False
        self._download_dir = Path.home() / "satmasivo"
        self._download_dir.mkdir(exist_ok=True)
        self.ciec = CiecClient()
        self._logged_rfc = ""

        provider = apply_css()
        self.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.get_style_context().add_class("toolbar")
        root.pack_start(bar, False, False, 0)

        stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.btn_home = ToolButton("go-home", "Home")
        self.btn_rec = ToolButton("mail-inbox", "Recibidas")
        self.btn_emi = ToolButton("mail-send", "Emitidas")
        self.btn_home.connect("clicked", lambda *_: self.go_home())
        self.btn_rec.connect("clicked", lambda *_: self.set_sentido("recibidas"))
        self.btn_emi.connect("clicked", lambda *_: self.set_sentido("emitidas"))
        stack.pack_start(self.btn_home, False, False, 0)
        stack.pack_start(self.btn_rec, False, False, 0)
        stack.pack_start(self.btn_emi, False, False, 0)
        bar.pack_start(stack, False, False, 0)

        self.btn_desc = ToolButton("document-save", "Descargar")
        self.btn_rep = ToolButton("x-office-spreadsheet", "Reporte")
        self.btn_pdf = ToolButton("application-pdf", "XML a PDF")
        self.btn_folder = ToolButton("folder", "Reporte CFDi\nde una carpeta")
        self.btn_upd = ToolButton("software-update-available", "Actualizar")
        self.btn_desc.connect("clicked", self.on_descargar)
        self.btn_rep.connect("clicked", self.on_reporte_actual)
        self.btn_pdf.connect("clicked", self.on_xml_pdf)
        self.btn_folder.connect("clicked", self.on_reporte_carpeta)
        self.btn_upd.connect("clicked", self.on_actualizar)
        for b in (self.btn_desc, self.btn_rep, self.btn_pdf, self.btn_folder, self.btn_upd):
            bar.pack_start(b, False, False, 0)

        hint = Gtk.Label(
            label="Home = entra al SAT (RFC + CIEC + captcha).\n"
            "Luego Recibidas o Emitidas y Descargar."
        )
        hint.set_justify(Gtk.Justification.LEFT)
        hint.get_style_context().add_class("hint")
        hint.set_xalign(0)
        bar.pack_end(hint, True, True, 8)

        self.pages = Gtk.Stack()
        self.pages.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        root.pack_start(self.pages, True, True, 0)
        self.pages.add_named(self._build_login(), "home")
        self.pages.add_named(self._build_work(), "work")

        self.status = Gtk.Label(label="Home — login SAT", xalign=0)
        self.status.get_style_context().add_class("statusbar")
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        root.pack_end(self.status, False, False, 0)

        self.go_home()
        GLib.idle_add(self._reload_captcha)
        GLib.timeout_add_seconds(8, self._silent_update_check)

    def _build_login(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(36)
        box.set_margin_bottom(24)
        box.set_halign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Acceso por contraseña")
        title.get_style_context().add_class("login-title")
        box.pack_start(title, False, False, 0)
        sub = Gtk.Label(
            label="Misma CIEC del SAT. El captcha lo resuelves tú.\nNo guardamos la contraseña."
        )
        sub.set_justify(Gtk.Justification.CENTER)
        box.pack_start(sub, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        grid.set_halign(Gtk.Align.CENTER)
        box.pack_start(grid, False, False, 8)

        self.ent_rfc = Gtk.Entry()
        self.ent_rfc.set_placeholder_text("RFC")
        self.ent_rfc.set_width_chars(28)
        self.ent_pwd = Gtk.Entry(visibility=False)
        self.ent_pwd.set_placeholder_text("Contraseña CIEC")
        self.ent_cap = Gtk.Entry()
        self.ent_cap.set_placeholder_text("Escribe el captcha")
        self.img_cap = Gtk.Image()
        self.lbl_login = Gtk.Label(label="")
        self.lbl_login.set_line_wrap(True)

        grid.attach(Gtk.Label(label="RFC", xalign=1), 0, 0, 1, 1)
        grid.attach(self.ent_rfc, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Contraseña", xalign=1), 0, 1, 1, 1)
        grid.attach(self.ent_pwd, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Captcha", xalign=1), 0, 2, 1, 1)
        cap_box = Gtk.Box(spacing=8)
        cap_box.pack_start(self.img_cap, False, False, 0)
        btn_ref = Gtk.Button(label="Otro captcha")
        btn_ref.connect("clicked", lambda *_: self._reload_captcha())
        cap_box.pack_start(btn_ref, False, False, 0)
        grid.attach(cap_box, 1, 2, 1, 1)
        grid.attach(self.ent_cap, 1, 3, 1, 1)

        btn = Gtk.Button(label="Enviar")
        btn.get_style_context().add_class("suggested-action")
        btn.connect("clicked", self.on_login)
        grid.attach(btn, 1, 4, 1, 1)
        grid.attach(self.lbl_login, 1, 5, 1, 1)
        self.ent_cap.connect("activate", self.on_login)
        return box

    def _build_work(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(48)
        box.set_halign(Gtk.Align.CENTER)
        self.lbl_work = Gtk.Label(label="")
        self.lbl_work.set_justify(Gtk.Justification.CENTER)
        self.lbl_work.set_line_wrap(True)
        box.pack_start(self.lbl_work, False, False, 0)
        return box

    def _mark(self, which: str) -> None:
        for name in ("btn_home", "btn_rec", "btn_emi"):
            getattr(self, name).get_style_context().remove_class("active")
        getattr(self, which).get_style_context().add_class("active")

    def go_home(self) -> None:
        self._mark("btn_home")
        self.pages.set_visible_child_name("home")
        self._set_status("Home — login SAT")

    def set_sentido(self, sentido: str, navigate: bool = True) -> None:
        self.sentido = sentido
        self._mark("btn_rec" if sentido == "recibidas" else "btn_emi")
        if not self._logged_rfc:
            self.go_home()
            self.lbl_login.set_text("Entra en Home primero (RFC + contraseña + captcha).")
            return
        self.pages.set_visible_child_name("work")
        self.lbl_work.set_text(
            f"Sesión {self._logged_rfc}\nModo {sentido}.\nPulsa Descargar."
        )
        self._set_status(f"Modo {sentido} · {self._logged_rfc}")

    def _set_status(self, text: str) -> None:
        self.status.set_text(text)

    def _reload_captcha(self) -> bool:
        self.lbl_login.set_text("Cargando captcha del SAT…")

        def work():
            try:
                img = self.ciec.start()
                GLib.idle_add(self._show_captcha, img, "")
            except Exception as exc:
                GLib.idle_add(self._show_captcha, b"", str(exc))

        threading.Thread(target=work, daemon=True).start()
        return False

    def _show_captcha(self, data: bytes, err: str) -> bool:
        if err:
            self.lbl_login.set_text(err)
            return False
        pb = pixbuf_from_bytes(data)
        if pb:
            self.img_cap.set_from_pixbuf(pb)
            self.lbl_login.set_text("")
        else:
            self.lbl_login.set_text("No se pudo pintar el captcha.")
        return False

    def on_login(self, *_a) -> None:
        rfc = self.ent_rfc.get_text().strip()
        pwd = self.ent_pwd.get_text()
        cap = self.ent_cap.get_text().strip()
        if not rfc or not pwd or not cap:
            self.lbl_login.set_text("Llena RFC, contraseña y captcha.")
            return
        self.lbl_login.set_text("Entrando al SAT…")

        def work():
            try:
                got = self.ciec.login(rfc, pwd, cap)
                GLib.idle_add(self._login_ok, got)
            except Exception as exc:
                GLib.idle_add(self._login_fail, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _login_ok(self, rfc: str) -> bool:
        self._logged_rfc = rfc
        self.ent_pwd.set_text("")
        self.ent_cap.set_text("")
        self.lbl_login.set_text(f"Sesión {rfc}")
        self.set_sentido(self.sentido)
        self._info("Sesión SAT", f"Entraste como {rfc}. Ya puedes Descargar.")
        return False

    def _login_fail(self, msg: str) -> bool:
        self.lbl_login.set_text(msg)
        pb = pixbuf_from_bytes(self.ciec.captcha)
        if pb:
            self.img_cap.set_from_pixbuf(pb)
        return False

    def _info(self, title: str, message: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=title,
        )
        dlg.format_secondary_text(message)
        dlg.run()
        dlg.destroy()

    def _error(self, message: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text="Error",
        )
        dlg.format_secondary_text(message)
        dlg.run()
        dlg.destroy()

    def _pick_folder(self, title: str) -> str | None:
        dlg = Gtk.FileChooserDialog(title=title, parent=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        res = dlg.run()
        path = dlg.get_filename() if res == Gtk.ResponseType.OK else None
        dlg.destroy()
        return path

    def _pick_file(self, title: str, patterns: list[tuple[str, str]]) -> str | None:
        dlg = Gtk.FileChooserDialog(title=title, parent=self, action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        for name, pat in patterns:
            filt = Gtk.FileFilter()
            filt.set_name(name)
            filt.add_pattern(pat)
            dlg.add_filter(filt)
        res = dlg.run()
        path = dlg.get_filename() if res == Gtk.ResponseType.OK else None
        dlg.destroy()
        return path

    def _pick_save(self, title: str, suggested: str) -> str | None:
        dlg = Gtk.FileChooserDialog(title=title, parent=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dlg.set_current_name(suggested)
        dlg.set_do_overwrite_confirmation(True)
        res = dlg.run()
        path = dlg.get_filename() if res == Gtk.ResponseType.OK else None
        dlg.destroy()
        return path

    def _ask_yes_no(self, text: str) -> bool:
        dlg = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=text,
        )
        res = dlg.run()
        dlg.destroy()
        return res == Gtk.ResponseType.YES

    def on_reporte_carpeta(self, *_a) -> None:
        folder = self._pick_folder("Carpeta con XML")
        if not folder:
            return
        dest = self._pick_save("Guardar Excel", "reporte-cfdi.xlsx")
        if not dest:
            return
        validar = self._ask_yes_no("¿Consultar vigencia en el SAT de cada UUID?")
        self._run_bg("Generando reporte…", lambda: self._job_reporte(folder, dest, validar))

    def on_reporte_actual(self, *_a) -> None:
        default = str(self._download_dir)
        if any(Path(default).rglob("*.xml")):
            dest = self._pick_save("Guardar Excel", "reporte-cfdi.xlsx")
            if not dest:
                return
            validar = self._ask_yes_no("¿Consultar vigencia en el SAT de cada UUID?")
            self._run_bg("Generando reporte…", lambda: self._job_reporte(default, dest, validar))
            return
        self.on_reporte_carpeta()

    def on_xml_pdf(self, *_a) -> None:
        xml = self._pick_file("CFDI XML", [("XML", "*.xml")])
        if not xml:
            return
        dest = self._pick_save("Guardar PDF", Path(xml).with_suffix(".pdf").name)
        if not dest:
            return
        try:
            cfdi_to_pdf(xml, dest)
            self._info("PDF listo", dest)
        except Exception as exc:
            self._error(str(exc))

    def on_descargar(self, *_a) -> None:
        dlg = Gtk.Dialog(title="Descargar del SAT", transient_for=self, flags=0)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Descargar", Gtk.ResponseType.OK)
        dlg.set_default_size(560, 400)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        radio_ciec = Gtk.RadioButton.new_with_label(None, "Sesión SAT (la de Home)")
        radio_fiel = Gtk.RadioButton.new_with_label_from_widget(radio_ciec, "e.firma (.cer + .key) — Web Service")
        box.pack_start(radio_ciec, False, False, 0)
        box.pack_start(radio_fiel, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        box.pack_start(grid, True, True, 0)

        def labeled(row: int, text: str, widget: Gtk.Widget) -> Gtk.Widget:
            grid.attach(Gtk.Label(label=text, xalign=1), 0, row, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, row, 1, 1)
            return widget

        cer = Gtk.FileChooserButton(title=".cer", action=Gtk.FileChooserAction.OPEN)
        key = Gtk.FileChooserButton(title=".key", action=Gtk.FileChooserAction.OPEN)
        pwd = Gtk.Entry(visibility=False, placeholder_text="Contraseña de la e.firma")
        ini = Gtk.Entry(text=datetime.now().replace(day=1).strftime("%Y-%m-%d"))
        fin = Gtk.Entry(text=datetime.now().strftime("%Y-%m-%d"))
        tipo = Gtk.ComboBoxText()
        for t in ("CFDI", "Metadata"):
            tipo.append_text(t)
        tipo.set_active(0)
        estado = Gtk.ComboBoxText()
        for t in ("Todos", "Vigente", "Cancelado"):
            estado.append_text(t)
        estado.set_active(0)
        dest = Gtk.FileChooserButton(title="Carpeta destino", action=Gtk.FileChooserAction.SELECT_FOLDER)
        dest.set_filename(str(self._download_dir))
        validar = Gtk.CheckButton(label="Validar vigencia en el SAT al terminar", active=True)
        labeled(0, "Certificado .cer", cer)
        labeled(1, "Llave .key", key)
        labeled(2, "Contraseña FIEL", pwd)
        labeled(3, "Fecha inicial", ini)
        labeled(4, "Fecha final", fin)
        labeled(5, "Tipo (e.firma)", tipo)
        labeled(6, "Estado (e.firma)", estado)
        labeled(7, "Destino", dest)
        grid.attach(validar, 1, 8, 1, 1)

        def toggle(*_):
            use_fiel = radio_fiel.get_active()
            for w in (cer, key, pwd, tipo, estado):
                w.set_sensitive(use_fiel)

        radio_ciec.connect("toggled", toggle)
        toggle()
        dlg.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return
        args = {
            "modo": "fiel" if radio_fiel.get_active() else "ciec",
            "cer": cer.get_filename(),
            "key": key.get_filename(),
            "pwd": pwd.get_text(),
            "ini": ini.get_text().strip(),
            "fin": fin.get_text().strip(),
            "tipo": tipo.get_active_text(),
            "estado": estado.get_active_text(),
            "dest": dest.get_filename(),
            "validar": validar.get_active(),
            "sentido": self.sentido,
        }
        dlg.destroy()
        if not args["dest"]:
            self._error("Falta carpeta destino.")
            return
        self._download_dir = Path(args["dest"])
        if args["modo"] == "fiel":
            if not args["cer"] or not args["key"] or not args["pwd"]:
                self._error("Para e.firma hacen falta .cer, .key y contraseña.")
                return
            self._run_bg("Descargando por e.firma…", lambda: self._job_descarga_fiel(args))
            return
        if not self._logged_rfc:
            self._error("Entra en Home primero.")
            return
        cookies = self.ciec.cookie_tuples()
        self._run_bg("Descargando con sesión SAT…", lambda: self._job_descarga_ciec(args, cookies))

    def on_actualizar(self, *_a) -> None:
        self._run_bg("Buscando actualización…", self._job_check_update)

    def _silent_update_check(self) -> bool:
        def work():
            try:
                rel = check_latest()
            except Exception:
                return
            if rel:
                GLib.idle_add(self._set_status, f"Hay {rel.tag} disponible. Pulsa Actualizar.")

        threading.Thread(target=work, daemon=True).start()
        return False

    def _ask_token(self) -> str | None:
        dlg = Gtk.Dialog(title="Token de GitHub", transient_for=self, flags=0)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_margin_top(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.pack_start(
            Gtk.Label(label="Repo privado. Token con lectura de releases, o gh auth login.", xalign=0),
            False, False, 0,
        )
        entry = Gtk.Entry(visibility=False)
        box.pack_start(entry, False, False, 8)
        dlg.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return None
        tok = entry.get_text().strip()
        dlg.destroy()
        if tok:
            save_token(tok)
        return tok or None

    def _run_bg(self, status: str, fn) -> None:
        if self._busy:
            self._error("Ya hay una operación en curso.")
            return
        self._busy = True
        self._set_status(status)

        def wrap():
            try:
                msg = fn()
                GLib.idle_add(self._done, True, msg)
            except Exception as exc:
                GLib.idle_add(self._done, False, f"{exc}\n\n{traceback.format_exc()}")

        threading.Thread(target=wrap, daemon=True).start()

    def _done(self, ok: bool, msg: str) -> bool:
        self._busy = False
        self._set_status("Listo" if ok else "Error")
        if msg == "__RESTART__":
            self._restart()
            return False
        if msg == "__NEED_TOKEN__":
            if self._ask_token():
                self._run_bg("Buscando actualización…", self._job_check_update)
            return False
        if ok:
            self._info("Listo", msg)
        else:
            self._error(msg)
        return False

    def _job_reporte(self, folder: str, dest: str, validar: bool) -> str:
        rows = scan_folder(folder)
        if not rows:
            raise SatError(f"No hay XML de CFDI en {folder}")
        if validar:
            rows = validar_rows(rows)
        export_excel(rows, dest)
        return f"{len(rows)} comprobantes → {dest}"

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
        dest = Path(args["dest"]) / fiel.rfc / args["sentido"] / args["ini"]
        dest.mkdir(parents=True, exist_ok=True)
        last = None
        for _ in range(90):
            last = client.verificar(sol.id_solicitud)
            GLib.idle_add(self._set_status, f"{last.estado_nombre} · {last.numero_cfdis} CFDI")
            if last.estado == 3:
                break
            if last.estado in {4, 5, 6}:
                raise SatError(f"{last.estado_nombre}: {last.mensaje}")
            time.sleep(20)
        else:
            raise SatError(f"Sigue en proceso. Id {sol.id_solicitud}.")
        extracted: list[str] = []
        for paq in last.paquetes:
            blob = client.descargar_paquete(paq)
            (dest / f"{paq}.zip").write_bytes(blob)
            extracted.extend(extraer_zip(blob, str(dest)))
        return self._finish_rows(dest, args["validar"], fiel.rfc, extra=f"Solicitud {sol.id_solicitud}\n")

    def _job_descarga_ciec(self, args: dict, cookies: list) -> str:
        dest = Path(args["dest"]) / "sesion-sat" / args["sentido"] / args["ini"]
        files = descargar_con_sesion(cookies, sentido=args["sentido"], dest=dest)
        return self._finish_rows(dest, args["validar"], self._logged_rfc, extra=f"{len(files)} XML por sesión SAT\n")

    def _finish_rows(self, dest: Path, validar: bool, rfc: str | None, extra: str = "") -> str:
        rows = scan_folder(dest)
        if validar and rows:
            rows = validar_rows(rows)
        if rows:
            export_excel(rows, dest / "reporte.xlsx", rfc_firma=rfc)
        return f"{extra}{len(rows)} comprobantes\n{dest}"

    def _job_check_update(self) -> str:
        try:
            rel = check_latest()
        except PermissionError:
            return "__NEED_TOKEN__"
        if rel is None:
            return f"Ya estás en {__version__}."
        path = download_deb(rel)
        install_deb(path)
        return "__RESTART__"

    def _restart(self) -> None:
        import shutil

        found = shutil.which("satmasivo")
        if found:
            os.execv(found, [found])
        os.execv(sys.executable, [sys.executable, "-m", "satmasivo"])


def main() -> None:
    try:
        win = SatMasivoWindow()
        win.connect("destroy", Gtk.main_quit)
        win.show_all()
        Gtk.main()
    except Exception as exc:
        sys.stderr.write(f"satmasivo: {exc}\n{traceback.format_exc()}")
        try:
            dlg = Gtk.MessageDialog(
                flags=0, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text="SAT Masivo no pudo abrir",
            )
            dlg.format_secondary_text(str(exc))
            dlg.run()
            dlg.destroy()
        except Exception:
            pass
        raise SystemExit(1)
