# SAT Masivo

Cliente Ubuntu de descarga masiva de CFDI.

## Uso

1. **Home** — login oficial del SAT (RFC + contraseña + captcha, o e.firma).
2. **Recibidas / Emitidas** — ya con sesión.
3. **Descargar** — sesión SAT de la ventana, o e.firma (WS).
4. **Actualizar** — baja el `.deb` del release.

## Instalar

```bash
sudo apt install ./satmasivo_1.2.0_all.deb
satmasivo
```

Si no abre, córrelo en terminal.

El SAT usa DH de 1024 bits. El launcher fuerza TLS compatible (GnuTLS + OpenSSL SECLEVEL=1).
