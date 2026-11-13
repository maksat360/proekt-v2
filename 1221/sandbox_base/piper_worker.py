# -*- coding: utf-8 -*-
"""Голос Джарвиса через Piper (локально, без интернета). Запускается Python-ом из ~/.jarvis-voice.

Голос грузится один раз (аргумент — путь к .onnx); по строке JSON {"text", "out"} пишет wav в out
и отвечает {"ok": true}. Темп чуть медленнее обычного — спокойная речь дворецкого.
"""
import json
import sys
import wave

from piper import PiperVoice, SynthesisConfig

VOICE = PiperVoice.load(sys.argv[1])
CFG = SynthesisConfig(length_scale=1.12, noise_scale=0.6, noise_w_scale=0.7)
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    try:
        job = json.loads(line)
        with wave.open(job["out"], "wb") as wf:
            VOICE.synthesize_wav(job["text"], wf, syn_config=CFG)
        out = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        out = {"error": str(exc)}
    print(json.dumps(out, ensure_ascii=False), flush=True)
