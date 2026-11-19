"""Håller KB-Whisper (svenska m.fl.) laddad i minnet och transkriberar över HTTP, bara på 127.0.0.1.

    POST /transcribe?language=sv     kropp: en ljudfil (wav, flac, ogg ...)  ->  {"text": ..., "seconds": ...}
         &task=translate             översätt till engelska (bara modeller som kan det, t.ex. whisper-large-v3)
         &model=whisper-large-v3     annan modell än standard: en mapp i ASR_MODELS_DIR (standard ~/models)
    GET  /load?model=...             ladda en modell i förväg (utan model: standardmodellen)
    GET  /health                     ->  {"ok": true, "model": ..., "loaded": [...]}

Bara en modell ligger i minnet åt gången: byts modell släpps den förra. Att ladda tar under en sekund.

Startas av launchd (~/Library/LaunchAgents/local.audio.asr.plist). Port: ASR_PORT (standard 8092).
"""
import gc, io, json, os, threading, time, warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import librosa, numpy as np, soundfile as sf, torch
from transformers import StoppingCriteria, StoppingCriteriaList, pipeline
from transformers.utils import logging
logging.set_verbosity_error(); logging.disable_progress_bar()

MODEL = os.path.expanduser(os.environ.get("ASR_MODEL", "~/models/kb-whisper-large"))
MODELS_DIR = os.path.expanduser(os.environ.get("ASR_MODELS_DIR", "~/models"))
PORT = int(os.environ.get("ASR_PORT", "8092"))
MAX_BYTES = 200 * 1024 * 1024                       # 200 MB ljud räcker långt
dev = "mps" if torch.backends.mps.is_available() else "cpu"

models = {}                                          # modellnamn -> (pipeline, suppress_tokens), högst en
lock = threading.Lock()                              # en transkribering (eller laddning) åt gången på GPU:n


def load(path):
    """Laddar en Whisper-modell och släpper den som låg inne förut. Anropas med lock hållet."""
    name = os.path.basename(path)
    if name not in models:
        if models:
            models.clear(); gc.collect()
            if dev == "mps":
                torch.mps.empty_cache()
        t = time.time()
        asr = pipeline("automatic-speech-recognition", model=path, dtype=torch.float16 if dev == "mps" else torch.float32,
                       device=dev, chunk_length_s=30)
        # Förbjud tidsstämpel-tokens. På brus genererar Whisper annars bara "<|0.00|><|3.00|>" utan text, och
        # transformers börjar om på samma segment i all oändlighet (GPU:n på ~90 % tills någon dödar processen).
        # (Skickas med i varje anrop: pipelinen har en egen kopia av generation_config.)
        g = asr.model.generation_config
        sup = sorted(set(g.suppress_tokens or []) | set(range(g.no_timestamps_token_id + 1, asr.model.config.vocab_size)))
        models[name] = (asr, sup)
        print(f"asr: {name} laddad på {dev} på {time.time()-t:.1f} s", flush=True)
    return models[name]


def model_path(name):
    """Ett modellnamn från en förfrågan -> en mapp i MODELS_DIR, eller None om det inte är en Whisper-modell där."""
    if not name:
        return MODEL
    p = os.path.join(MODELS_DIR, name)
    ok = name == os.path.basename(name) and not name.startswith(".") and os.path.isfile(os.path.join(p, "config.json"))
    return p if ok else None


load(MODEL)
print(f"asr: lyssnar på 127.0.0.1:{PORT}", flush=True)


def decode(data: bytes):
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
    except Exception:                                # format soundfile inte kan: låt librosa försöka
        audio, sr = librosa.load(io.BytesIO(data), sr=None, mono=True)
    return librosa.resample(audio, orig_sr=sr, target_sr=16000) if sr != 16000 else audio


def has_speech(audio, frame=800, level=0.005, min_frames=3):
    """Minst ~0,15 s (3 x 50 ms) med ljud över brusgolvet. Whisper hittar på text, eller fastnar i
    upprepningar i minuter, när den får tystnad, så tyst ljud skrivs inte ut alls."""
    n = len(audio) // frame
    if n == 0:
        return False
    rms = np.sqrt((audio[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
    return int((rms > level).sum()) >= min_frames


class Deadline(StoppingCriteria):
    """Stoppar genereringen efter en viss tid, oavsett vad modellen gör, och räknar stegen för loggen."""
    def __init__(self, seconds):
        self.end, self.steps = time.time() + seconds, 0

    def __call__(self, input_ids, scores, **kw):
        self.steps += 1
        return time.time() > self.end


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/load":
            path = model_path(parse_qs(u.query).get("model", [""])[0])
            if path is None:
                return self.reply(400, {"error": f"okänd modell; den ska ligga som en mapp i {MODELS_DIR}"})
            try:
                with lock:
                    load(path)
            except Exception as e:                    # noqa: BLE001
                print(f"asr: kunde inte ladda {path}: {e!r}", flush=True)
                return self.reply(500, {"error": repr(e)[:300]})
            return self.reply(200, {"ok": True, "loaded": sorted(models)})
        if u.path == "/health":
            return self.reply(200, {"ok": True, "model": os.path.basename(MODEL), "loaded": sorted(models), "device": dev})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/transcribe":
            return self.reply(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BYTES:
            return self.reply(400, {"error": "skicka en ljudfil som kropp (högst 200 MB)"})
        q = parse_qs(u.query)
        lang = q.get("language", ["sv"])[0]
        task = q.get("task", ["transcribe"])[0]
        path = model_path(q.get("model", [""])[0])
        if task not in ("transcribe", "translate"):
            return self.reply(400, {"error": "task ska vara transcribe eller translate"})
        if path is None:
            return self.reply(400, {"error": f"okänd modell; den ska ligga som en mapp i {MODELS_DIR}"})
        try:
            audio = decode(self.rfile.read(n))
            t = time.time()
            if not has_speech(audio):
                print(f"asr: {len(audio)/16000:.1f} s ljud utan tal, hoppar över", flush=True)
                return self.reply(200, {"text": "", "language": lang, "seconds": 0.0, "silent": True})
            # tak för genererade tokens: snabbt tal är ~5 tokens/s, så 12/s + 24 räcker gott men
            # hindrar en upprepningsslinga från att hålla på i minuter
            cap = min(440, int(len(audio) / 16000 * 12) + 24)
            with lock:
                asr, sup = load(path)
                t = time.time()
                dl = Deadline(max(10.0, 2.0 * len(audio) / 16000))   # normalt ~0,2 s per sekund ljud
                text = asr({"raw": audio, "sampling_rate": 16000},
                           generate_kwargs={"task": task, "language": lang, "max_new_tokens": cap, "suppress_tokens": sup,
                                            "stopping_criteria": StoppingCriteriaList([dl])})["text"].strip()
                if dev == "mps":
                    torch.mps.empty_cache()           # lämna tillbaka arbetsminnet mellan förfrågningar
            secs = time.time() - t
            print(f"asr: {len(audio)/16000:.1f} s ljud ({lang}, {task}, {os.path.basename(path)}) på {secs:.2f} s, {dl.steps} steg", flush=True)
            if time.time() > dl.end:
                print(f"asr: AVBRÖT efter tidsgränsen. peak={np.abs(audio).max():.4f} rms={np.sqrt((audio**2).mean()):.4f} "
                      f"nan={int(np.isnan(audio).sum())} text={text[:200]!r}", flush=True)
            self.reply(200, {"text": text, "language": lang, "seconds": round(secs, 3)})
        except Exception as e:                        # noqa: BLE001
            print(f"asr: fel: {e!r}", flush=True)
            self.reply(500, {"error": repr(e)[:300]})


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
