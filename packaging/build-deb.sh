#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
VER="${1:-1.0.0}"
STAGE="$ROOT/packaging/pkg"
PKG="$STAGE/satmasivo"
rm -rf "$STAGE"
mkdir -p "$ROOT/dist" \
         "$PKG/DEBIAN" \
         "$PKG/usr/bin" \
         "$PKG/usr/lib/satmasivo" \
         "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/scalable/apps" \
         "$PKG/usr/share/doc/satmasivo"

cat > "$PKG/DEBIAN/control" <<EOF
Package: satmasivo
Version: $VER
Section: office
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, python3-lxml, python3-cryptography, python3-requests, python3-openpyxl, python3-reportlab, python3-pil
Maintainer: Daniel <hatysquarepants0310@users.noreply.github.com>
Description: Descarga masiva de CFDI del SAT para Ubuntu
 Cliente de escritorio para bajar, validar y reportar CFDI
 usando el Web Service oficial y el login SAT embebido.
EOF

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
exit 0
EOF
chmod 755 "$PKG/DEBIAN/postinst"

cp "$ROOT/packaging/satmasivo.desktop" "$PKG/usr/share/applications/"
cp "$ROOT/satmasivo/assets/satmasivo.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/satmasivo.svg"
cp "$ROOT/README.md" "$PKG/usr/share/doc/satmasivo/"
cp -a "$ROOT/satmasivo" "$PKG/usr/lib/satmasivo/"
find "$PKG/usr/lib/satmasivo" -type d -name '__pycache__' -prune -exec rm -rf {} +

cat > "$PKG/usr/bin/satmasivo" <<'EOF'
#!/usr/bin/python3
import os
import sys
os.environ.setdefault(
    "G_TLS_GNUTLS_PRIORITY",
    "NORMAL:-DHE-RSA:-DHE-DSS:%COMPAT:%PROFILE_VERY_WEAK",
)
os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
sys.path.insert(0, "/usr/lib/satmasivo")
from satmasivo.__main__ import main
if __name__ == "__main__":
    main()
EOF
chmod 755 "$PKG/usr/bin/satmasivo"

dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/satmasivo_${VER}_all.deb"
echo "built $ROOT/dist/satmasivo_${VER}_all.deb"
ls -lh "$ROOT/dist/satmasivo_${VER}_all.deb"
