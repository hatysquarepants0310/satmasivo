"""Ventana principal: barra tipo Masiva + portal SAT embebido."""

from __future__ import annotations

import os
import threading
import traceback
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, Pango, WebKit2

from satmasivo import __version__
from satmasivo.cfdi import scan_folder
from satmasivo.excel import export_excel
from satmasivo.fiel import load_fiel
from satmasivo.pdf import cfdi_to_pdf, folder_to_pdf
from satmasivo.sat_ws import SatError, SatMasiva, extraer_zip
from satmasivo.validar import validar_rows

SAT_LOGIN = (
    "https://cfdiau.sat.gob.mx/nidp/wsfed/ep"
    "?id=SATUPCFDiCon&sid=0&option=credential&sid=0"
)
SAT_PORTAL = "https://portalcfdi.facturaelectronica.sat.gob.mx/"
BLUE = "#0078D4"


def _css() -> None:
    css = f"""
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
    .hint {{
        background: {BLUE};
        color: #ffffff;
        font-weight: 700;
        padding: 4px 12px;
        font-size: 13px;
    }}
    .statusbar {{
        background: #f3f3f3;
        padding: 2px 8px;
        font-size: 11px;
    }}
    """.encode()
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gtk.StyleContext.get_default() and Gtk.Window().get_screen(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


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
        self.set_default_size(1180, 760)
        self.sentido = "recibidas"
        self._busy = False

        _css()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.get_style_context().add_class("toolbar")
        root.pack_start(bar, False, False, 0)

        stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.btn_rec = ToolButton("mail-inbox", "Recibidas")
        self.btn_emi = ToolButton("mail-send", "Emitidas")
        self.btn_rec.connect("clicked", lambda *_: self.set_sentido("recibidas"))
        self.btn_emi.connect("clicked", lambda *_: self.set_sentido("emitidas"))
        stack.pack_start(self.btn_rec, False, False, 0)
        stack.pack_start(self.btn_emi, False, False, 0)
        bar.pack_start(stack, False, False, 0)

        self.btn_desc = ToolButton("document-save", "Descargar")
        self.btn_rep = ToolButton("x-office-spreadsheet", "Reporte")
        self.btn_pdf = ToolButton("application-pdf", "XML a PDF")
        self.btn_folder = ToolButton("folder", "Reporte CFDi\nde una carpeta")
        self.btn_desc.connect("clicked", self.on_descargar)
        self.btn_rep.connect("clicked", self.on_reporte_actual)
        self.btn_pdf.connect("clicked", self.on_xml_pdf)
        self.btn_folder.connect("clicked", self.on_reporte_carpeta)
        for b in (self.btn_desc, self.btn_rep, self.btn_pdf, self.btn_folder):
            bar.pack_start(b, False, False, 0)

        hint = Gtk.Label(label="Entra con tu RFC y contraseña SAT o e.firma.\nEl captcha lo resuelves tú. SAT Masivo hace el resto.")
        hint.set_justify(Gtk.Justification.LEFT)
        hint.get_style_context().add_class("hint")
        hint.set_xalign(0)
        bar.pack_end(hint, True, True, 8)

        self.webview = WebKit2.WebView()
        settings = self.webview.get_settings()
        settings.set_enable_javascript(True)
        settings.set_user_agent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        self.webview.connect("notify::uri", self._on_uri)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.webview)
        root.pack_start(scroll, True, True, 0)

        self.status = Gtk.Label(label=SAT_LOGIN, xalign=0)
        self.status.get_style_context().add_class("statusbar")
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        root.pack_end(self.status, False, False, 0)

        self.set_sentido("recibidas")
        self.webview.load_uri(SAT_LOGIN)

    def set_sentido(self, sentido: str) -> None:
        self.sentido = sentido
        self.btn_rec.get_style_context().remove_class("active")
        self.btn_emi.get_style_context().remove_class("active")
        (self.btn_rec if sentido == "recibidas" else self.btn_emi).get_style_context().add_class("active")
        self._set_status(f"Modo {sentido}. {self.webview.get_uri() or SAT_LOGIN}")

    def _on_uri(self, *_args) -> None:
        uri = self.webview.get_uri() or ""
        self._set_status(uri)

    def _set_status(self, text: str) -> None:
        self.status.set_text(text)

    def _info(self, title: str, message: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dlg.format_secondary_text(message)
        dlg.run()
        dlg.destroy()

    def _error(self, message: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dlg.format_secondary_text(message)
        dlg.run()
        dlg.destroy()

    def _pick_folder(self, title: str) -> str | None:
        dlg = Gtk.FileChooserDialog(
            title=title,
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
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
        default = str(Path.home() / "satmasivo")
        if Path(default).exists():
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

    def _ask_yes_no(self, text: str) -> bool:
        dlg = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=text,
        )
        res = dlg.run()
        dlg.destroy()
        return res == Gtk.ResponseType.YES

    def on_descargar(self, *_a) -> None:
        dlg = Gtk.Dialog(title="Descargar del SAT", transient_for=self, flags=0)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Descargar", Gtk.ResponseType.OK)
        dlg.set_default_size(520, 360)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8, margin=14)
        dlg.get_content_area().pack_start(grid, True, True, 0)

        def labeled(row: int, text: str, widget: Gtk.Widget) -> Gtk.Widget:
            grid.attach(Gtk.Label(label=text, xalign=1), 0, row, 1, 1)
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
        dest.set_filename(str(Path.home() / "satmasivo"))
        Path.home().joinpath("satmasivo").mkdir(exist_ok=True)
        validar = Gtk.CheckButton(label="Validar vigencia en el SAT al terminar", active=True)

        labeled(0, "Certificado .cer", cer)
        labeled(1, "Llave .key", key)
        labeled(2, "Contraseña FIEL", pwd)
        labeled(3, "Fecha inicial", ini)
        labeled(4, "Fecha final", fin)
        labeled(5, "Tipo", tipo)
        labeled(6, "Estado", estado)
        labeled(7, "Destino", dest)
        grid.attach(validar, 1, 8, 1, 1)
        note = Gtk.Label(
            label="La e.firma viaja solo al SAT. No se guarda en disco ni en la firma.",
            xalign=0,
        )
        note.set_line_wrap(True)
        grid.attach(note, 0, 9, 2, 1)
        dlg.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return
        args = {
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
        if not args["cer"] or not args["key"] or not args["pwd"] or not args["dest"]:
            self._error("Faltan .cer, .key, contraseña o carpeta destino.")
            return
        self._run_bg("Descargando del SAT…", lambda: self._job_descarga(args))

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

    def _job_descarga(self, args: dict) -> str:
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
        # poll
        import time

        last = None
        for _ in range(90):
            last = client.verificar(sol.id_solicitud)
            GLib.idle_add(self._set_status, f"{last.estado_nombre} · {last.numero_cfdis} CFDI · {sol.id_solicitud}")
            if last.estado == 3:
                break
            if last.estado in {4, 5, 6}:
                raise SatError(f"{last.estado_nombre}: {last.mensaje}")
            time.sleep(20)
        else:
            raise SatError(
                f"Sigue {last.estado_nombre if last else 'en proceso'}. "
                f"IdSolicitud {sol.id_solicitud}. Vuelve a Descargar más tarde; el SAT puede tardar horas."
            )
        extracted: list[str] = []
        for paq in last.paquetes:
            blob = client.descargar_paquete(paq)
            zip_path = dest / f"{paq}.zip"
            zip_path.write_bytes(blob)
            extracted.extend(extraer_zip(blob, str(dest)))
        rows = scan_folder(dest)
        if args["validar"] and rows:
            rows = validar_rows(rows)
        xlsx = dest / "reporte.xlsx"
        if rows:
            export_excel(rows, xlsx, rfc_firma=fiel.rfc)
        return (
            f"RFC {fiel.rfc}\n"
            f"Solicitud {sol.id_solicitud}\n"
            f"{last.numero_cfdis} CFDI · {len(extracted)} archivos\n"
            f"{dest}"
        )


def main() -> None:
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
    win = SatMasivoWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
