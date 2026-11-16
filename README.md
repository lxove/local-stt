# lokal-ai

Lokal AI på en MacBook Pro M5 Max (128 GB). Röst och språkmodell körs på datorn, och inget ljud lämnar den.

| Del | Vad | Var det körs |
|---|---|---|
| **Diktering** | Dubbeltryck på fn startar, ett tryck stoppar, och texten klistras in där markören står. Ersätter Apples diktering. | Hammerspoon + `rost/diktera_rec.py` + ASR-tjänsten |
| **ASR-tjänst** | KB-Whisper large (svenska) laddad i minnet, HTTP på `127.0.0.1:8092` | launchd `local.audio.asr` |
| **`lyssna`** | Tal till text från mikrofon eller fil. Svenska via tjänsten, engelska via ARK-ASR-3B med `--en`. | terminal |
| **`tala`** | Text till tal med Audio8-TTS-Realistic-Air (23 språk, svenska ingår) och röstkloning | terminal |
| **Edge0 145B** | Språkmodell, OpenAI-kompatibelt API på `127.0.0.1:8080`, 128K kontext | launchd `local.edge0.serve` |
| **OpenCode** | Agentharness mot Edge0 145B | `opencode/opencode.json` |

Repot innehåller bara kod och konfiguration. Modellerna (cirka 17 GB för röst och 41 GB för 145B), Python-miljön och apparna installeras enligt nedan.

## Installation

### 1. Verktyg

```sh
brew install uv
brew install --cask hammerspoon
uv tool install huggingface_hub     # ger kommandot hf
```

### 2. Röstdelen

```sh
cd ~/projects/lokal-ai
./install.sh --venv --modeller
```

Skriptet gör följande:

- skapar `~/models/audio-venv` från `requirements.txt`
- laddar ner modellerna till `~/models`
- länkar `tala` och `lyssna` till `~/.local/bin`
- länkar Hammerspoon-konfigurationen till `~/.hammerspoon`
- installerar och startar `local.audio.asr`

Skriptet går att köra igen. Utan flaggor gör det bara länkarna och tjänsten.

### 3. Behörigheter och fn-tangenten (görs för hand)

1. Systeminställningar → Integritet och säkerhet → **Hjälpmedel**: slå på **Hammerspoon**. Ladda sedan om konfigurationen via hammaren i menyraden → Reload Config.
2. Systeminställningar → Tangentbord → "Tryck på 🌐-tangenten för att": välj **Gör ingenting**, annars startar Apples diktering också.
3. Första gången du dikterar frågar macOS om **Mikrofon** för Hammerspoon. Svara ja.
4. Hammerspoon → Preferences → **Launch at login** (eller `hs -c 'hs.autoLaunch(true)'`).

### 4. Edge0 145B (valfritt)

Bygg edge0 enligt dess egen dokumentation i `~/projects/edge0`:

- edge0-strata: [Build (macOS, Apple Silicon)](https://github.com/Edge0-AI/Edge0/blob/main/edge0-strata/EDGE0.md#build-macos-apple-silicon) (`build-metal/` och `.venv`)
- edge0-infer: `cmake --preset mac-metal && cmake --build --preset mac-metal`

Hämta modellen och installera tjänsten:

```sh
hf download Edge0/Edge0-145B-q3k --local-dir ~/models/Edge0-145B-q3k
./install.sh --edge0
```

Tjänsten startar `edge0-infer serve` med `--context 131072`. Mallens standard är 32K. 128K är verifierat med nåltest vid cirka 125K tokens (3/3), och minnestoppen är då cirka 30 GB.

### 5. OpenCode (valfritt)

```sh
cp opencode/opencode.json ~/.config/opencode/opencode.json
opencode service restart
```

Konfigurationen pekar OpenCode mot Edge0 på 8080. Titelagenten körs utan thinking, annars köar den framför din första fråga. Den innehåller också två interna MCP-servrar: `pg` (utan auth) och `manager` (avstängd tills auth är löst). Ta bort dem om de inte finns i ditt nätverk.

## Användning

**Diktering:** dubbeltryck på **fn** startar. Ett "Tink" spelas och 🎙 i menyraden blir 🔴. Ett tryck på **fn** stoppar: ⏳ visas, och sedan klistras texten in. **Esc** avbryter. fn tillsammans med en annan tangent (fn+pil, fn+Delete, fn+F …) räknas inte. Det du hade i urklipp läggs tillbaka efteråt.

Inställningar finns överst i `hammerspoon/diktera.lua`:

| | Standard | |
|---|---|---|
| `TAP_MAX` | 0.35 s | längsta tid fn får hållas för att räknas som ett tryck |
| `DOUBLE_GAP` | 0.45 s | längsta tid mellan två tryck i ett dubbeltryck |
| `START_SOUND` | `"Tink"` | systemljud vid start (`/System/Library/Sounds`), `nil` = tyst |
| `SOUND_VOLUME` | 0.35 | |

Byt dikteringsspråk med `ASR_LANG` i `diktera.lua` (Whisper-koder: `sv`, `en`, `no`, `da`, `fi` …).

**Terminal:**

```sh
lyssna                         # spela in tills Enter, svenska
lyssna fil.wav                 # transkribera en fil
lyssna --en                    # engelska (ARK-ASR-3B, laddas lokalt)
lyssna --spara min-rost.wav    # spara inspelningen också

tala "Hej, hur mår du?"                                   # ny slumpad röst varje gång
tala "Hej igen" --ref min-rost.wav --ref-text "exakt det som sägs i min-rost.wav"   # klona en röst
```

För kloning: läs en svensk mening som referens, annars får rösten engelsk brytning. Texten i `--ref-text` måste stämma ordagrant.

## Så fungerar det

```
fn fn ─▶ Hammerspoon ──"start"──▶ diktera_rec.py ──mikrofon──▶ minnet
fn    ─▶ Hammerspoon ──"stop"───▶ diktera_rec.py ──wav (POST)──▶ asr_server.py (KB-Whisper, MPS, fp16)
                                                    ◀──{"text"}──
         Hammerspoon ◀──{"text"}── ⌘V där markören står
```

- **Inget ljud på disk.** Inspelningen hålls i minnet och skickas som wav över `127.0.0.1`. Det enda undantaget är `lyssna --en` och `--lokalt`, som skapar en tillfällig fil och tar bort den direkt.
- **Varma processer.** ASR-tjänsten (cirka 3,5 GB i vila och 6 GB under arbete) och inspelningsklienten (några tiotal MB) är alltid igång, så dikteringen svarar på cirka 1 s för 6 s tal. Mikrofonen är bara öppen under inspelning.
- **float16.** KB-Whisper och ARK-ASR körs i float16. Testat på fem svenska klipp gav det ordagrant samma text som float32, med halva minnet. `tala` körs i float32. `AUDIO_DTYPE=float16|float32` styr båda.
- **Fjärrkod.** Audio8-TTS och ARK-ASR kräver `trust_remote_code`. Koden i modellmapparna granskades (inga nätverksanrop eller skalkommandon, och codec-filen laddas med `weights_only=True`). Allt körs med `HF_HUB_OFFLINE=1`.

## Modeller

| Modell | Uppgift | Språk | Disk | Minne | Licens |
|---|---|---|---:|---:|---|
| [KBLab/kb-whisper-large](https://huggingface.co/KBLab/kb-whisper-large) | tal till text | svenska (+ Whispers språk) | 3,0 GB | 3,5 GB vila / 6 GB (fp16) | Apache-2.0 |
| [Edge0/ARK-ASR-3B](https://huggingface.co/Edge0/ARK-ASR-3B) | tal till text | 19 språk, **inte svenska** | 7,6 GB | 11,5 GB (fp16) | Apache-2.0 |
| [Edge0/Audio8-TTS-Realistic-Air](https://huggingface.co/Edge0/Audio8-TTS-Realistic-Air) | text till tal, kloning | 23 språk inkl. svenska | 5,9 GB | 7,2 GB (fp32) | Apache-2.0 |
| [Edge0/Edge0-145B-q3k](https://huggingface.co/Edge0/Edge0-145B-q3k) | språkmodell | | 41 GB | ~27–30 GB | se modellkortet |

## Felsökning

| Problem | Gör så här |
|---|---|
| Inget händer på fn fn | Kontrollera att Hammerspoon har Hjälpmedel och kör Reload Config. Ställ in "Tryck på 🌐" på *Gör ingenting*. |
| "ASR-tjänsten svarar inte" | `curl 127.0.0.1:8092/health`, loggen finns i `~/Library/Logs/audio-asr.log`. Starta om med `launchctl kickstart -k gui/$(id -u)/local.audio.asr`. |
| Tom text | Mikrofonbehörighet för Hammerspoon, eller fel ingång i Systeminställningar → Ljud → Ingång. |
| Inspelaren har hängt sig | Menyraden 🎙 → *Starta om inspelaren*. |
| Stänga av tjänster | `launchctl bootout gui/$(id -u)/local.audio.asr` (respektive `local.edge0.serve`) |

## Filer

```
bin/tala, bin/lyssna            skalskript, länkas till ~/.local/bin
rost/asr_server.py              ASR-tjänsten (KB-Whisper)
rost/diktera_rec.py             varm inspelningsklient för Hammerspoon
rost/lyssna.py, rost/tala.py    terminalkommandona
rost/roundtrip_test.py          test: tal av text och sedan text av talet igen (lägger wav i ~/models/audio-test)
hammerspoon/                    init.lua + diktera.lua, länkas till ~/.hammerspoon
launchd/*.plist                 mallar (__HOME__, __REPO__, __EDGE0__) som install.sh fyller i
opencode/opencode.json          OpenCode-konfiguration för Edge0
requirements.txt                Python-paket för ~/models/audio-venv
```
