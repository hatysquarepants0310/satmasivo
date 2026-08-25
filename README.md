# SAT Masivo

Cliente Ubuntu de descarga masiva de CFDI. Cada quien entra con **su** SAT.

Privado. Para la firma.

## Qué hace

- Barra: Recibidas / Emitidas / Descargar / Reporte / XML a PDF / Reporte de carpeta / Actualizar.
- Login oficial del SAT embebido. El captcha lo resuelve el usuario. CIEC no se guarda.
- **Descargar** en dos modos:
  - Sesión SAT (RFC + contraseña de la ventana).
  - e.firma (`.cer` + `.key`) por el Web Service oficial.
- Excel: ingresos / egresos / pagos, IVA/IEPS/ISR, forma de pago, complemento de pago, vigencia.
- **Actualizar** baja el `.deb` del release de GitHub e instala con `pkexec`. Repo privado: token o `gh auth login`.

## Instalar

```bash
sudo apt install ./satmasivo_1.1.0_all.deb
satmasivo
```

Si no abre, córrelo en terminal: el error sale ahí y en un diálogo.

## Uso

1. Entra al SAT (RFC + contraseña + captcha, o e.firma).
2. Recibidas o Emitidas.
3. Descargar: elige sesión SAT o e.firma, fechas y carpeta.
4. Actualizar cuando haya release nuevo.
