"""Inspelningsklient för diktering via Hammerspoon. Hålls igång (varm) och styrs med en rad per kommando på stdin:

    start    öppna mikrofonen och börja spela in (i minnet)
    stop     stäng mikrofonen, skicka ljudet till ASR-tjänsten, svara med en JSON-rad {"text": ...} eller {"error": ...}
    cancel   stäng mikrofonen och släng ljudet, svara {"cancelled": true}

Inget ljud skrivs till disk. ASR-tjänsten: ASR_URL (standard http://127.0.0.1:8092), språk: ASR_LANG (standard sv).
"""
import io, json, os, sys, threading, urllib.error, urllib.request

import numpy as np, sounddevice as sd, soundfile as sf

URL = os.environ.get("ASR_URL", "http://127.0.0.1:8092")
LANG = os.environ.get("ASR_LANG", "sv")
SR = 16000
lock = threading.Lock()
chunks, stream = [], None


def say(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n"); sys.stdout.flush()


def on_audio(data, frames, time_info, status):
    with lock:
        chunks.append(data.copy())


def close_stream():
    global stream
    if stream is not None:
        stream.stop(); stream.close(); stream = None
    with lock:
        audio = np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, np.float32)
        chunks.clear()
    return audio


def transcribe(audio):
    buf = io.BytesIO(); sf.write(buf, audio, SR, format="WAV")
    req = urllib.request.Request(f"{URL}/transcribe?language={LANG}", data=buf.getvalue(),
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["text"]


say({"ready": True})
for line in sys.stdin:
    cmd = line.strip()
    try:
        if cmd == "start":
            close_stream()
            stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=on_audio)
            stream.start()
            say({"recording": True})
        elif cmd == "stop":
            audio = close_stream()
            if len(audio) < SR // 3:                 # under en tredjedels sekund: inget att skriva
                say({"text": "", "seconds": len(audio) / SR})
            else:
                say({"text": transcribe(audio), "seconds": round(len(audio) / SR, 1)})
        elif cmd == "cancel":
            close_stream(); say({"cancelled": True})
    except urllib.error.URLError as e:
        say({"error": f"ASR-tjänsten svarar inte ({e.reason}); är local.audio.asr igång?"})
    except Exception as e:                            # noqa: BLE001
        say({"error": repr(e)[:300]})
