"""TTS (Audio8-TTS-Realistic-Air) -> wav -> ASR (ARK-ASR-3B), lokalt på Apple Silicon (MPS), offline."""
import time, sys, soundfile as sf, torch
from transformers import AutoModel, AutoProcessor, AutoModelForCausalLM, AutoTokenizer
import os
M = os.path.expanduser("~/models"); OUT = f"{M}/audio-test"
dev = "mps" if torch.backends.mps.is_available() else "cpu"

t = time.time()
tp = AutoProcessor.from_pretrained(f"{M}/Audio8-TTS-Realistic-Air", trust_remote_code=True)
tts = AutoModel.from_pretrained(f"{M}/Audio8-TTS-Realistic-Air", trust_remote_code=True, dtype=torch.float32).eval().to(dev)
print(f"TTS laddad på {dev} på {time.time()-t:.1f} s", flush=True)
texts = {"sv": "Hej! Det här är en lokal talsyntes som körs på din Mac.",
         "en": "This speech was generated locally and then transcribed again."}
for lang, text in texts.items():
    inp = {k: v.to(dev) for k, v in tp(text=[text], return_tensors="pt").items()}
    t = time.time()
    with torch.inference_mode():
        o = tts.generate(**inp, max_new_tokens=1024, temperature=0.8, top_p=0.95, top_k=50, do_sample=True, return_dict_in_generate=True)
        w, n = tts.decode_audio(o.codes)
    a = w[0, :int(n[0])].float().cpu().numpy(); sr = tts.config.codec_sample_rate
    sf.write(f"{OUT}/tts-{lang}.wav", a, sr)
    print(f"TTS {lang}: {len(a)/sr:.1f} s ljud på {time.time()-t:.1f} s -> {OUT}/tts-{lang}.wav", flush=True)
del tts; torch.mps.empty_cache() if dev == "mps" else None

t = time.time()
ap = AutoProcessor.from_pretrained(f"{M}/ARK-ASR-3B", trust_remote_code=True)
tok = AutoTokenizer.from_pretrained(f"{M}/ARK-ASR-3B", trust_remote_code=True)
asr = AutoModelForCausalLM.from_pretrained(f"{M}/ARK-ASR-3B", trust_remote_code=True, torch_dtype=torch.float32, attn_implementation="sdpa").to(dev).eval()
print(f"ASR laddad på {dev} på {time.time()-t:.1f} s", flush=True)
eos = tok.eos_token_id; keep = {eos} if isinstance(eos, int) else set(eos or [])
bad = (set(tok.all_special_ids) - keep) | {i for s, i in tok.get_added_vocab().items() if s.startswith("<") and s.endswith(">") and i not in keep}
for lang in texts:
    conv = [{"role": "user", "content": [{"type": "audio", "path": f"{OUT}/tts-{lang}.wav"}, {"type": "text", "text": "Please transcribe this audio."}]}]
    inp = ap.apply_chat_template(conv, add_generation_prompt=True, return_tensors="pt", sampling_rate=16000, audio_padding="longest", text_kwargs={"padding": "longest"}, audio_max_length=30*16000).to(dev)
    if "audios" in inp: inp["audios"] = inp["audios"].to(dtype=torch.float32)
    t = time.time()
    with torch.inference_mode():
        out = asr.generate(**inp, do_sample=False, max_new_tokens=256, pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id, bad_words_ids=[[i] for i in sorted(bad)])
    txt = tok.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0]
    print(f"ASR {lang} ({time.time()-t:.1f} s): {txt!r}\n   original: {texts[lang]!r}", flush=True)
