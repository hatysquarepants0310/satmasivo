# SAT Masivo

Cliente Ubuntu de descarga masiva de CFDI. Misma idea que *Descarga Masiva CFDi* de erpDOZ: cada quien entra con **su** SAT y el programa baja, valida y saca Excel.

Privado. Para la firma.

## Qué hace

- Pantalla principal: barra Recibidas / Emitidas / Descargar / Reporte / XML a PDF / Reporte de carpeta, y el login oficial del SAT embebido (`cfdiau.sat.gob.mx`). El captcha lo resuelve el usuario. La contraseña CIEC no la guardamos.
- **Descargar** usa el Web Service oficial del SAT (v1.5) con e.firma (`.cer` + `.key` + contraseña). No hay scrape del portal.
- Extrae los ZIP, arma Excel ordenado (Todos / Ingresos / Egresos / Pagos) y opcionalmente consulta vigencia (vigente / cancelada).
- Columnas: UUID, fechas, RFCs y nombres, serie/folio, moneda, TC, subtotal, descuento, IVA/IEPS/ISR trasladados y retenidos, totales, forma y método de pago, uso CFDI, complemento de pago, estatus SAT.

La e.firma no se sube a GitHub, no se escribe en el vault y no se queda en disco.

## Instalar

Release `v1.0.0` en este repo:

```bash
sudo apt install ./satmasivo_1.0.0_all.deb
satmasivo
```

Dependencias de sistema: GTK 3, WebKitGTK 4.1, Python 3.11+.

## Uso

1. Abre SAT Masivo. Entra al SAT (RFC + contraseña + captcha, o e.firma en esa misma página).
2. Elige Recibidas o Emitidas.
3. **Descargar**: apunta tu `.cer` / `.key`, fechas y carpeta. El SAT puede tardar minutos u horas; el programa espera y baja los paquetes.
4. **Reporte de una carpeta** si ya tienes XML.
5. **XML a PDF** para una representación impresa.

## Desarrollo

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e . pytest
PYTHONPATH=. pytest -q
python -m satmasivo
```

Paquete:

```bash
bash packaging/build-deb.sh 1.0.0
```
