# -*- coding: utf-8 -*-
"""Распознавание речи для Джарвиса: запускается Python-ом OpenJarvis (там есть faster-whisper).

Модель грузится один раз; по строке JSON {"path": файл} в stdin отвечает {"text": ...} в stdout.
Всё локально, звук никуда не уходит.
"""
import json
import sys

from faster_whisper import WhisperModel

MODEL = WhisperModel(sys.argv[1] if len(sys.argv) > 1 else "base", device="cpu", compute_type="int8")
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    try:
        path = json.loads(line)["path"]
        segs, _ = MODEL.transcribe(path, language="ru", beam_size=1, vad_filter=True)
        out = {"text": "".join(s.text for s in segs).strip()}
    except Exception as exc:  # noqa: BLE001
        out = {"error": str(exc)}
    print(json.dumps(out, ensure_ascii=False), flush=True)
