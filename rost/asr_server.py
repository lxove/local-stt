"""Håller KB-Whisper (svenska m.fl.) laddad i minnet och transkriberar över HTTP, bara på 127.0.0.1.

    POST /transcribe?language=sv     kropp: en ljudfil (wav, flac, ogg ...)  ->  {"text": ..., "seconds": ...}
    GET  /health                     ->  {"ok": true, "model": ...}

Startas av launchd (~/Library/LaunchAgents/local.audio.asr.plist). Port: ASR_PORT (standard 8092).
"""
import io, json, os, threading, time, warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import librosa, soundfile as sf, torch
from transformers import pipeline
from transformers.utils import logging
logging.set_verbosity_error(); logging.disable_progress_bar()

MODEL = os.path.expanduser(os.environ.get("ASR_MODEL", "~/models/kb-whisper-large"))
PORT = int(os.environ.get("ASR_PORT", "8092"))
MAX_BYTES = 200 * 1024 * 1024                       # 200 MB ljud räcker långt
dev = "mps" if torch.backends.mps.is_available() else "cpu"

t = time.time()
asr = pipeline("automatic-speech-recognition", model=MODEL, dtype=torch.float16 if dev == "mps" else torch.float32,
               device=dev, chunk_length_s=30)
lock = threading.Lock()                              # en transkribering åt gången på GPU:n
print(f"asr: {os.path.basename(MODEL)} laddad på {dev} på {time.time()-t:.1f} s, lyssnar på 127.0.0.1:{PORT}", flush=True)


def decode(data: bytes):
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
    except Exception:                                # format soundfile inte kan: låt librosa försöka
        audio, sr = librosa.load(io.BytesIO(data), sr=None, mono=True)
    return librosa.resample(audio, orig_sr=sr, target_sr=16000) if sr != 16000 else audio


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            return self.reply(200, {"ok": True, "model": os.path.basename(MODEL), "device": dev})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/transcribe":
            return self.reply(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BYTES:
            return self.reply(400, {"error": "skicka en ljudfil som kropp (högst 200 MB)"})
        lang = parse_qs(u.query).get("language", ["sv"])[0]
        try:
            audio = decode(self.rfile.read(n))
            t = time.time()
            with lock:
                text = asr({"raw": audio, "sampling_rate": 16000},
                           generate_kwargs={"task": "transcribe", "language": lang})["text"].strip()
                if dev == "mps":
                    torch.mps.empty_cache()           # lämna tillbaka arbetsminnet mellan förfrågningar
            secs = time.time() - t
            print(f"asr: {len(audio)/16000:.1f} s ljud ({lang}) på {secs:.2f} s", flush=True)
            self.reply(200, {"text": text, "language": lang, "seconds": round(secs, 3)})
        except Exception as e:                        # noqa: BLE001
            print(f"asr: fel: {e!r}", flush=True)
            self.reply(500, {"error": repr(e)[:300]})


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
