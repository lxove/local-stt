#!/bin/sh
# Installerar det här repot på en Mac (Apple Silicon). Kör från repots rot. Säkert att köra igen.
#
#   ./install.sh            kommandon, Hammerspoon-config och röst-tjänsten (förutsätter modeller och venv)
#   ./install.sh --venv     skapa/uppdatera ~/models/audio-venv från requirements.txt först
#   ./install.sh --modeller ladda också ner röstmodellerna (~17 GB) med hf
#   ./install.sh --edge0    installera också launchd-agenten för edge0-servern (kräver ett byggt edge0, se README)
#
# Miljö: EDGE0_DIR (standard ~/projects/edge0), AUDIO_VENV (standard ~/models/audio-venv)
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
EDGE0=${EDGE0_DIR:-$HOME/projects/edge0}
VENV=${AUDIO_VENV:-$HOME/models/audio-venv}
LA=$HOME/Library/LaunchAgents
UID_=$(id -u)
VENV_FLAG=0; MODELS=0; WITH_EDGE0=0
for a in "$@"; do case $a in
  --venv) VENV_FLAG=1 ;; --modeller) MODELS=1 ;; --edge0) WITH_EDGE0=1 ;;
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
  say "Röstmodeller till ~/models (hf download)"
  command -v hf >/dev/null || { echo "hf saknas: uv tool install huggingface_hub" >&2; exit 1; }
  hf download Edge0/Audio8-TTS-Realistic-Air --local-dir "$HOME/models/Audio8-TTS-Realistic-Air"
  hf download Edge0/ARK-ASR-3B --local-dir "$HOME/models/ARK-ASR-3B"
  hf download KBLab/kb-whisper-large --local-dir "$HOME/models/kb-whisper-large" \
    --include "*.json" "model.safetensors" "merges.txt" "vocab.json" "README.md"
fi

say "Kommandon: tala, lyssna -> ~/.local/bin"
mkdir -p "$HOME/.local/bin"
for c in tala lyssna; do ln -sfn "$REPO/bin/$c" "$HOME/.local/bin/$c"; done

say "Hammerspoon-config -> ~/.hammerspoon"
mkdir -p "$HOME/.hammerspoon"
for f in init.lua diktera.lua; do
  t=$HOME/.hammerspoon/$f
  if [ -e "$t" ] && [ ! -L "$t" ]; then mv "$t" "$t.bak.$(date +%s)"; echo "  sparade din gamla $f som $f.bak.*"; fi
  ln -sfn "$REPO/hammerspoon/$f" "$t"
done
[ -d /Applications/Hammerspoon.app ] || echo "  Hammerspoon saknas: brew install --cask hammerspoon"

render() {   # mall i launchd/ -> ~/Library/LaunchAgents, och (om)ladda agenten
  label=$1
  mkdir -p "$LA" "$HOME/Library/Logs/edge0"
  sed -e "s|__REPO__|$REPO|g; s|__EDGE0__|$EDGE0|g; s|__HOME__|$HOME|g" "$REPO/launchd/$label.plist" > "$LA/$label.plist"
  plutil -lint "$LA/$label.plist" >/dev/null
  launchctl bootout "gui/$UID_/$label" 2>/dev/null || true
  i=0; while launchctl print "gui/$UID_/$label" >/dev/null 2>&1 && [ $i -lt 30 ]; do sleep 0.5; i=$((i+1)); done
  launchctl bootstrap "gui/$UID_" "$LA/$label.plist"
  echo "  $label laddad"
}

say "Tjänst: local.audio.asr (KB-Whisper på 127.0.0.1:8092)"
[ -x "$VENV/bin/python" ] || { echo "  $VENV saknas: kör ./install.sh --venv" >&2; exit 1; }
[ -f "$HOME/models/kb-whisper-large/model.safetensors" ] || echo "  varning: KB-Whisper saknas (./install.sh --modeller)"
render local.audio.asr

if [ $WITH_EDGE0 = 1 ]; then
  say "Tjänst: local.edge0.serve (Edge0 145B på 127.0.0.1:8080)"
  [ -x "$EDGE0/edge0-infer/build/mac-metal/bin/edge0-infer" ] || { echo "  edge0-infer är inte byggt i $EDGE0 (se README)" >&2; exit 1; }
  render local.edge0.serve
fi

[ -L "$HOME/.hammerspoon/init.lua" ] && command -v hs >/dev/null && (hs -t 3 -c 'hs.reload()' >/dev/null 2>&1 &) || true
say "Klart. Se README.md för behörigheter (Hjälpmedel, Mikrofon) och fn-inställningen."
