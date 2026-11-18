#!/bin/sh
# Installerar dikteringen på en Mac (Apple Silicon). Kör från repots rot. Säkert att köra igen.
#
#   ./install.sh            Hammerspoon-config och ASR-tjänsten (förutsätter modell och venv)
#   ./install.sh --venv     skapa/uppdatera ~/models/audio-venv från requirements.txt först
#   ./install.sh --modeller ladda också ner KB-Whisper large (~3 GB) med hf
#
# Miljö: AUDIO_VENV (standard ~/models/audio-venv)
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
VENV=${AUDIO_VENV:-$HOME/models/audio-venv}
LA=$HOME/Library/LaunchAgents
UID_=$(id -u)
LABEL=local.audio.asr
VENV_FLAG=0; MODELS=0
for a in "$@"; do case $a in
  --venv) VENV_FLAG=1 ;; --modeller) MODELS=1 ;;
  *) echo "okänd flagga: $a" >&2; exit 2 ;;
esac; done

say() { printf '\n== %s\n' "$*"; }

if [ $VENV_FLAG = 1 ]; then
  say "Python-miljö: $VENV"
  command -v uv >/dev/null || { echo "uv saknas: brew install uv" >&2; exit 1; }
  [ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV"
  VIRTUAL_ENV=$VENV uv pip install -r "$REPO/requirements.txt"
fi

if [ $MODELS = 1 ]; then
  say "KB-Whisper large till ~/models (hf download)"
  command -v hf >/dev/null || { echo "hf saknas: uv tool install huggingface_hub" >&2; exit 1; }
  hf download KBLab/kb-whisper-large --local-dir "$HOME/models/kb-whisper-large" \
    --include "*.json" "model.safetensors" "merges.txt" "vocab.json" "README.md"
fi

say "Python-miljö -> $REPO/.venv"
[ -x "$VENV/bin/python" ] || { echo "  $VENV saknas: kör ./install.sh --venv" >&2; exit 1; }
if [ "$VENV" != "$REPO/.venv" ]; then
  [ -e "$REPO/.venv" ] && [ ! -L "$REPO/.venv" ] && { echo "  $REPO/.venv finns redan och är ingen länk" >&2; exit 1; }
  ln -sfn "$VENV" "$REPO/.venv"
fi

say "Hammerspoon-config -> ~/.hammerspoon"
HS=$HOME/.hammerspoon
mkdir -p "$HS"
t=$HS/diktera.lua
if [ -e "$t" ] && [ ! -L "$t" ]; then mv "$t" "$t.bak.$(date +%s)"; echo "  sparade din gamla diktera.lua som diktera.lua.bak.*"; fi
ln -sfn "$REPO/hammerspoon/diktera.lua" "$t"
if [ ! -e "$HS/init.lua" ]; then
  ln -sfn "$REPO/hammerspoon/init.lua" "$HS/init.lua"; echo "  init.lua länkad"
elif grep -q 'require("diktera")' "$HS/init.lua"; then
  echo "  init.lua laddar redan diktera"
else                         # behåll din egen init.lua och lägg bara till dikteringen sist
  printf '\n-- lokal-stt: diktering med fn fn\nrequire("hs.ipc")\ndiktera = require("diktera")\ndiktera.start()\n' >> "$HS/init.lua"
  echo "  lade till diktering sist i din init.lua"
fi
[ -d /Applications/Hammerspoon.app ] || echo "  Hammerspoon saknas: brew install --cask hammerspoon"

say "Tjänst: $LABEL (KB-Whisper på 127.0.0.1:8092)"
[ -f "$HOME/models/kb-whisper-large/model.safetensors" ] || echo "  varning: KB-Whisper saknas (./install.sh --modeller)"
mkdir -p "$LA" "$HOME/Library/Logs"
sed -e "s|__REPO__|$REPO|g; s|__HOME__|$HOME|g; s|__VENV__|$VENV|g" "$REPO/launchd/$LABEL.plist" > "$LA/$LABEL.plist"
plutil -lint "$LA/$LABEL.plist" >/dev/null
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
i=0; while launchctl print "gui/$UID_/$LABEL" >/dev/null 2>&1 && [ $i -lt 30 ]; do sleep 0.5; i=$((i+1)); done
launchctl bootstrap "gui/$UID_" "$LA/$LABEL.plist"
echo "  $LABEL laddad"

command -v hs >/dev/null && (hs -t 3 -c 'hs.reload()' >/dev/null 2>&1 &) || true
say "macOS-inställningar"
fn=$(defaults read com.apple.HIToolbox AppleFnUsageType 2>/dev/null || echo "?")
dict=$(defaults read com.apple.assistant.support "Dictation Enabled" 2>/dev/null || echo "?")
[ "$fn" = 0 ] || echo "  VARNING: 🌐/fn-tangenten gör något annat än 'Gör ingenting' och krockar med fn fn."
[ "$dict" = 1 ] && echo "  VARNING: Apples diktering verkar vara påslagen och kan starta samtidigt."

cat <<'EOF'

Klart. Det här måste du göra för hand (se README.md, steg 3):
  1. Systeminställningar → Integritet och säkerhet → Hjälpmedel: slå på Hammerspoon,
     och kör sedan Reload Config via hammaren i menyraden.
  2. Systeminställningar → Tangentbord → Diktering: stäng av.
     Ställ också in "Tryck på 🌐-tangenten för att" på "Gör ingenting".
     Kontrollera båda igen efter macOS-uppdateringar, eftersom de kan slås på igen.
  3. Svara ja när macOS frågar om Mikrofon för Hammerspoon första gången du dikterar.
  4. Hammerspoon → Preferences → Launch at login.
EOF
