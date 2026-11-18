# local-stt

Lokal diktering på en Mac (Apple Silicon). Dubbeltryck på **fn** startar, ett tryck stoppar, och texten klistras in där markören står. Talet skrivs ut av Kungliga bibliotekets KB-Whisper large på datorn, och inget ljud lämnar den. Ersätter Apples diktering.

| Del | Vad | Var det körs |
|---|---|---|
| **Kortkommando** | fn fn startar, fn stoppar, Esc avbryter, texten klistras in | Hammerspoon (`hammerspoon/diktera.lua`) |
| **Inspelare** | varm process som spelar in från mikrofonen till minnet | `rost/diktera_rec.py`, startas av Hammerspoon |
| **ASR-tjänst** | KB-Whisper large (svenska) laddad i minnet, HTTP på `127.0.0.1:8092` | launchd `local.audio.asr` |

Repot innehåller bara kod och konfiguration. Modellen (cirka 3 GB), Python-miljön och Hammerspoon installeras enligt nedan.

## Installation

### 1. Verktyg

```sh
brew install uv
brew install --cask hammerspoon
uv tool install huggingface_hub     # ger kommandot hf
```

### 2. Diktering

```sh
git clone https://github.com/lxove/local-stt.git lokal-stt
cd lokal-stt
./install.sh --venv --modeller
```

Skriptet gör följande:

- skapar `~/models/audio-venv` från `requirements.txt` (annan plats: `AUDIO_VENV=...`) och länkar den som `.venv` i repot
- laddar ner KB-Whisper large till `~/models/kb-whisper-large`
- länkar `diktera.lua` till `~/.hammerspoon`. Har du redan en `init.lua` läggs dikteringen till sist i den, annars länkas repots.
- installerar och startar `local.audio.asr`

Repot kan ligga var som helst. Flyttar du det, kör `./install.sh` igen. Skriptet går att köra igen, och utan flaggor gör det bara länkarna och tjänsten.

### 3. Behörigheter och fn-tangenten (görs för hand)

1. Systeminställningar → Integritet och säkerhet → **Hjälpmedel**: slå på **Hammerspoon**. Ladda sedan om konfigurationen via hammaren i menyraden → Reload Config.
2. Systeminställningar → Tangentbord → **Diktering**: stäng av. Ställ också in "Tryck på 🌐-tangenten för att" på **Gör ingenting**. Annars startar Apples diktering samtidigt. Kontrollera båda igen efter macOS-uppdateringar, eftersom de kan slås på igen.
3. Första gången du dikterar frågar macOS om **Mikrofon** för Hammerspoon. Svara ja.
4. Hammerspoon → Preferences → **Launch at login** (eller `hs -c 'hs.autoLaunch(true)'`).

## Användning

Dubbeltryck på **fn** startar. Ett "Tink" spelas och 🎙 i menyraden blir 🔴. Ett tryck på **fn** stoppar: ⏳ visas, och sedan klistras texten in. **Esc** avbryter. fn tillsammans med en annan tangent (fn+pil, fn+Delete, fn+F …) räknas inte. Det du hade i urklipp läggs tillbaka efteråt.

Inställningar finns överst i `hammerspoon/diktera.lua`:

| | Standard | |
|---|---|---|
| `TAP_MAX` | 0.35 s | längsta tid fn får hållas för att räknas som ett tryck |
| `DOUBLE_GAP` | 0.45 s | längsta tid mellan två tryck i ett dubbeltryck |
| `START_SOUND` | `"Tink"` | systemljud vid start (`/System/Library/Sounds`), `nil` = tyst |
| `SOUND_VOLUME` | 0.35 | |

Byt dikteringsspråk med `ASR_LANG` i `diktera.lua` (Whisper-koder: `sv`, `en`, `no`, `da`, `fi` …).

## Så fungerar det

```
fn fn ─▶ Hammerspoon ──"start"──▶ diktera_rec.py ──mikrofon──▶ minnet
fn    ─▶ Hammerspoon ──"stop"───▶ diktera_rec.py ──wav (POST)──▶ asr_server.py (KB-Whisper, MPS, fp16)
                                                    ◀──{"text"}──
         Hammerspoon ◀──{"text"}── ⌘V där markören står
```

- **Inget ljud på disk.** Inspelningen hålls i minnet och skickas som wav över `127.0.0.1`.
- **Varma processer.** ASR-tjänsten (cirka 3,5 GB i vila och 6 GB under arbete) och inspelaren (några tiotal MB) är alltid igång, så dikteringen svarar på cirka 1 s för 6 s tal. Mikrofonen är bara öppen under inspelning.
- **float16.** KB-Whisper körs i float16 på MPS. Testat på fem svenska klipp gav det ordagrant samma text som float32, med halva minnet.
- **Tystnad.** Ljud utan tal skickas inte till modellen, eftersom Whisper annars hittar på text eller fastnar i upprepningar.
- **Offline.** Tjänsten körs med `HF_HUB_OFFLINE=1`.

## Modell

| Modell | Språk | Disk | Minne | Licens |
|---|---|---:|---:|---|
| [KBLab/kb-whisper-large](https://huggingface.co/KBLab/kb-whisper-large) | svenska (+ Whispers språk) | 3,0 GB | 3,5 GB vila / 6 GB (fp16) | Apache-2.0 |

## Felsökning

| Problem | Gör så här |
|---|---|
| Inget händer på fn fn | Kontrollera att Hammerspoon har Hjälpmedel och kör Reload Config. Ställ in "Tryck på 🌐" på *Gör ingenting*. |
| Apples diktering startar igen (ofta efter en macOS-uppdatering) | macOS kan slå på sin egen diktering igen. Stäng av Systeminställningar → Tangentbord → Diktering och ställ in "Tryck på 🌐" på *Gör ingenting* igen. |
| "ASR-tjänsten svarar inte" | `curl 127.0.0.1:8092/health`, loggen finns i `~/Library/Logs/audio-asr.log`. Starta om med `launchctl kickstart -k gui/$(id -u)/local.audio.asr`. |
| Tom text | Mikrofonbehörighet för Hammerspoon, eller fel ingång i Systeminställningar → Ljud → Ingång. |
| Inspelaren har hängt sig | Menyraden 🎙 → *Starta om inspelaren*. |
| Stänga av tjänsten | `launchctl bootout gui/$(id -u)/local.audio.asr` |

## Filer

```
hammerspoon/                    init.lua + diktera.lua, länkas till ~/.hammerspoon
rost/diktera_rec.py             varm inspelningsklient för Hammerspoon
rost/asr_server.py              ASR-tjänsten (KB-Whisper)
launchd/local.audio.asr.plist   mall (__HOME__, __REPO__, __VENV__) som install.sh fyller i
requirements.txt                Python-paket för ~/models/audio-venv
install.sh                      installation
```
