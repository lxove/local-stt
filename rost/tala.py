"""Läs upp text med Audio8-TTS-Realistic-Air.
    tala "Hej, hur mår du?"                          # standardröst
    tala "Hej igen" --ref min-rost.wav --ref-text "Exakt det jag sa i inspelningen."   # klona en röst
    tala "Hello" --out hej.wav --no-play
"""
import argparse, os, subprocess, tempfile, time, warnings
warnings.filterwarnings("ignore")
import soundfile as sf, torch
from transformers import AutoModel, AutoProcessor
p = argparse.ArgumentParser(); p.add_argument("text"); p.add_argument("--ref"); p.add_argument("--ref-text")
p.add_argument("--out"); p.add_argument("--no-play", action="store_true"); a = p.parse_args()
if bool(a.ref) != bool(a.ref_text): p.error("--ref och --ref-text måste anges tillsammans")
M = os.path.expanduser("~/models/Audio8-TTS-Realistic-Air"); dev = "mps" if torch.backends.mps.is_available() else "cpu"
DT = {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(os.environ.get("AUDIO_DTYPE", ""), torch.float32)
proc = AutoProcessor.from_pretrained(M, trust_remote_code=True)
model = AutoModel.from_pretrained(M, trust_remote_code=True, dtype=DT).eval().to(dev)
kw = dict(text=[a.text], return_tensors="pt")
if a.ref: kw.update(reference_audio=[a.ref], reference_text=[a.ref_text])
inp = {k: v.to(dev) for k, v in proc(**kw).items()}
t = time.time()
with torch.inference_mode():
    o = model.generate(**inp, max_new_tokens=1024, temperature=0.8, top_p=0.95, top_k=50, do_sample=True, return_dict_in_generate=True)
    w, n = model.decode_audio(o.codes)
audio = w[0, :int(n[0])].float().cpu().numpy(); sr = model.config.codec_sample_rate
out = a.out or tempfile.mktemp(suffix=".wav", prefix="tala-")
sf.write(out, audio, sr); print(f"{len(audio)/sr:.1f} s ljud på {time.time()-t:.1f} s -> {out}")
if not a.no_play: subprocess.run(["afplay", out])
