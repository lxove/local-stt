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

say "Hammerspoon-config -> ~/.hammerspoon"
mkdir -p "$HOME/.hammerspoon"
for f in init.lua diktera.lua; do
  t=$HOME/.hammerspoon/$f
  if [ -e "$t" ] && [ ! -L "$t" ]; then mv "$t" "$t.bak.$(date +%s)"; echo "  sparade din gamla $f som $f.bak.*"; fi
  ln -sfn "$REPO/hammerspoon/$f" "$t"
done
[ -d /Applications/Hammerspoon.app ] || echo "  Hammerspoon saknas: brew install --cask hammerspoon"

say "Tjänst: $LABEL (KB-Whisper på 127.0.0.1:8092)"
[ -x "$VENV/bin/python" ] || { echo "  $VENV saknas: kör ./install.sh --venv" >&2; exit 1; }
[ -f "$HOME/models/kb-whisper-large/model.safetensors" ] || echo "  varning: KB-Whisper saknas (./install.sh --modeller)"
mkdir -p "$LA" "$HOME/Library/Logs"
sed -e "s|__REPO__|$REPO|g; s|__HOME__|$HOME|g" "$REPO/launchd/$LABEL.plist" > "$LA/$LABEL.plist"
plutil -lint "$LA/$LABEL.plist" >/dev/null
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
i=0; while launchctl print "gui/$UID_/$LABEL" >/dev/null 2>&1 && [ $i -lt 30 ]; do sleep 0.5; i=$((i+1)); done
launchctl bootstrap "gui/$UID_" "$LA/$LABEL.plist"
echo "  $LABEL laddad"

[ -L "$HOME/.hammerspoon/init.lua" ] && command -v hs >/dev/null && (hs -t 3 -c 'hs.reload()' >/dev/null 2>&1 &) || true
say "Klart. Se README.md för behörigheter (Hjälpmedel, Mikrofon) och fn-inställningen."
