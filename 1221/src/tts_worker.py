# -*- coding: utf-8 -*-
"""Голос Джарвиса нейросетью Chatterbox Multilingual (MIT, Resemble AI) — локально, без интернета.

Запускается Python-ом из ~/.jarvis-voice. Модель грузится один раз; по строке JSON
{"text", "out", "ref"} пишет wav в out и отвечает {"ok": true}. ref — образец голоса (10–30 с wav),
пусто — встроенный голос модели. Тон: exaggeration (эмоции), cfg (темп/следование образцу).
"""
import json
import sys

import torch
import torchaudio as ta
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
_load = torch.load


def _cpu_load(*a, **k):  # веса сохранены под CUDA — грузим на CPU, потом переносим
    k.setdefault("map_location", torch.device("cpu"))
    return _load(*a, **k)


torch.load = _cpu_load
OUT = sys.stdout
sys.stdout = sys.stderr  # библиотеки печатают свои сообщения — stdout оставляем только для ответов
try:
    MODEL = ChatterboxMultilingualTTS.from_pretrained(device=DEVICE)
except Exception:  # noqa: BLE001 — MPS не завёлся: CPU медленнее, но работает
    DEVICE = "cpu"
    MODEL = ChatterboxMultilingualTTS.from_pretrained(device=DEVICE)
print(json.dumps({"ready": True, "device": DEVICE}), file=OUT, flush=True)

for line in sys.stdin:
    try:
        job = json.loads(line)
        kw = {"language_id": "ru", "exaggeration": float(job.get("exaggeration", 0.4)),
              "cfg_weight": float(job.get("cfg", 0.5))}
        if job.get("ref"):
            kw["audio_prompt_path"] = job["ref"]
        wav = MODEL.generate(job["text"], **kw)
        ta.save(job["out"], wav, MODEL.sr)
        out = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        out = {"error": str(exc)}
    print(json.dumps(out, ensure_ascii=False), file=OUT, flush=True)
