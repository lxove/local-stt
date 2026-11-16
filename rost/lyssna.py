"""Tal till text, lokalt och offline.
    lyssna                        # spela in från mikrofonen tills du trycker Enter (svenska, KB-Whisper)
    lyssna fil.wav                # transkribera en fil
    lyssna --spara min-rost.wav   # spela in, spara och transkribera (bra som --ref till tala)
    lyssna --en                   # engelska med ARK-ASR-3B i stället
    lyssna --sprak no             # annat språk med KB-Whisper (Whisper-kod: no, da, fi, en ...)
    lyssna --lokalt               # ladda modellen här i stället för att fråga tjänsten

KB-Whisper körs i tjänsten local.audio.asr (127.0.0.1:8092) om den är igång; annars laddas modellen här.
"""
import argparse, json, os, sys, tempfile, time, urllib.error, urllib.request, warnings
warnings.filterwarnings("ignore")

URL = os.environ.get("ASR_URL", "http://127.0.0.1:8092")
p = argparse.ArgumentParser()
p.add_argument("fil", nargs="?"); p.add_argument("--spara")
p.add_argument("--en", action="store_true", help="engelska med ARK-ASR-3B")
p.add_argument("--sprak", default="sv", help="språk för KB-Whisper (standard sv)")
p.add_argument("--lokalt", action="store_true", help="använd inte tjänsten")
a = p.parse_args()

path, wav = a.fil, None          # wav: inspelningen som wav-bytes i minnet (ingen fil om inte --spara)
if not path:
    import io, queue
    import numpy as np, sounddevice as sd, soundfile as sf
    q, chunks = queue.Queue(), []
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=lambda d, *_: q.put(d.copy())):
        input("Spelar in ... tryck Enter när du är klar. ")
    while not q.empty(): chunks.append(q.get())
    audio = np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, np.float32)
    if len(audio) < 8000: sys.exit("För kort inspelning (eller saknas mikrofonbehörighet för terminalen).")
    buf = io.BytesIO(); sf.write(buf, audio, 16000, format="WAV"); wav = buf.getvalue()
    if a.spara:
        with open(a.spara, "wb") as f: f.write(wav)
        path = a.spara
    print(f"{len(audio)/16000:.1f} s inspelat" + (f" -> {a.spara}" if a.spara else ""))


def ljud_bytes():
    if wav is not None: return wav
    with open(path, "rb") as f: return f.read()


def via_tjansten():
    """Texten från tjänsten, eller None om den inte är igång."""
    req = urllib.request.Request(f"{URL}/transcribe?language={a.sprak}", data=ljud_bytes(),
                                 headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["text"]
    except urllib.error.HTTPError as e:
        sys.exit(f"tjänsten svarade {e.code}: {e.read()[:300].decode(errors='replace')}")
    except (urllib.error.URLError, ConnectionError):
        return None


def lokalt(path, en):
    import torch, librosa
    from transformers.utils import logging
    logging.set_verbosity_error(); logging.disable_progress_bar()
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    DT = {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(os.environ.get("AUDIO_DTYPE", "float16"), torch.float32)
    if not en:
        from transformers import pipeline
        asr = pipeline("automatic-speech-recognition", model=os.path.expanduser("~/models/kb-whisper-large"),
                       dtype=DT, device=dev, chunk_length_s=30)
        audio, _ = librosa.load(path, sr=16000, mono=True)      # läs själv: pipelinen vill annars ha ffmpeg
        return asr({"raw": audio, "sampling_rate": 16000},
                   generate_kwargs={"task": "transcribe", "language": a.sprak})["text"].strip()
    from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer
    M = os.path.expanduser("~/models/ARK-ASR-3B")
    proc = AutoProcessor.from_pretrained(M, trust_remote_code=True); tok = AutoTokenizer.from_pretrained(M, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(M, trust_remote_code=True, dtype=DT, attn_implementation="sdpa").to(dev).eval()
    eos = tok.eos_token_id; keep = {eos} if isinstance(eos, int) else set(eos or [])
    bad = (set(tok.all_special_ids) - keep) | {i for s, i in tok.get_added_vocab().items() if s.startswith("<") and s.endswith(">") and i not in keep}
    conv = [{"role": "user", "content": [{"type": "audio", "path": path}, {"type": "text", "text": "Please transcribe this audio."}]}]
    inp = proc.apply_chat_template(conv, add_generation_prompt=True, return_tensors="pt", sampling_rate=16000, audio_padding="longest",
                                   text_kwargs={"padding": "longest"}, audio_max_length=30 * 16000).to(dev)
    if "audios" in inp: inp["audios"] = inp["audios"].to(dtype=DT)
    with torch.inference_mode():
        out = model.generate(**inp, do_sample=False, max_new_tokens=256, pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id,
                             bad_words_ids=[[i] for i in sorted(bad)])
    return tok.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0]


t = time.time()
text, kalla = None, "ARK-ASR-3B" if a.en else f"KB-Whisper {a.sprak}"
if not a.en and not a.lokalt:
    text = via_tjansten()
    if text is not None: kalla += ", tjänsten"
if text is None:
    tmp = None
    if path is None:                 # modellerna här vill ha en fil: en tillfällig som tas bort direkt efteråt
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="lyssna-"); os.write(fd, wav); os.close(fd)
    try:
        text = lokalt(path or tmp, a.en); kalla += ", lokalt"
    finally:
        if tmp: os.unlink(tmp)
print(text, f"   ({time.time()-t:.1f} s, {kalla})")
