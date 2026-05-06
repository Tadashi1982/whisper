#!/usr/bin/env bash
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dist/WhisperWriter"
APP_DIR="$HOME/.local/share/WhisperWriter"
DESKTOP_FILE="$HOME/.local/share/applications/whisperwriter.desktop"

if [ ! -d "$SRC" ]; then
    echo "Bundle nao encontrado em $SRC. Rode 'pyinstaller WhisperWriter.spec --noconfirm' primeiro."
    exit 1
fi

echo "Instalando em $APP_DIR..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$SRC"/. "$APP_DIR"/

mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=WhisperWriter
GenericName=Speech to Text
Comment=Ditado por voz com Whisper local (faster-whisper)
Exec=$APP_DIR/WhisperWriter
Icon=$APP_DIR/_internal/assets/ww-logo.png
Terminal=false
Categories=Utility;AudioVideo;
StartupNotify=true
Keywords=speech;voice;transcribe;dictation;whisper;
EOF

chmod +x "$DESKTOP_FILE"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Instalado."
echo "  Binario: $APP_DIR/WhisperWriter"
echo "  Atalho:  $DESKTOP_FILE"
echo "  Procure 'WhisperWriter' no menu de aplicativos do GNOME."
