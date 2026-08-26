# SAT Masivo

Mismo programa en Ubuntu (`.deb`) y Windows (`.exe` que se instala).

1. Home: RFC + CIEC + captcha.
2. Recibidas / Emitidas.
3. Descargar. *Reporte* = último lote. *Reporte de carpeta* = otra carpeta.

Al abrir, las dos versiones buscan el último release y se actualizan solas si hay uno más nuevo.

```bash
# Ubuntu
sudo apt install ./satmasivo_1.5.22_all.deb
satmasivo
```

Windows: corre `satmasivo.exe` del release una vez. Se instala en el usuario (`%LOCALAPPDATA%\Programs\SATMasivo`) y deja *SAT Masivo* en Inicio y en el escritorio. Después puedes borrar el descargado; se abre desde el menú. Las actualizaciones reemplazan esa copia instalada.
