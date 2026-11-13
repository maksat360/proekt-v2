# -*- coding: utf-8 -*-
"""Голос Джарвиса на сервере — одинаковый на всех устройствах.

Речь → текст: Whisper из OpenJarvis (отдельный процесс, модель держится в памяти).
Текст → речь: голос Yuri этого Мака (`say`), в m4a — играет и на iPhone, и на Android.
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
JARVIS_PY = Path.home() / ".openjarvis" / ".venv" / "bin" / "python"
VOICE = "Yuri"
_LOCK = threading.Lock()
_proc: subprocess.Popen | None = None


def stt_available() -> bool:
    return JARVIS_PY.exists()


def _worker() -> subprocess.Popen:
    global _proc
    if _proc is None or _proc.poll() is not None:
        _proc = subprocess.Popen([str(JARVIS_PY), "-I", str(HERE / "speech_worker.py"), "base"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding="utf-8")
        ready = _proc.stdout.readline()
        if '"ready"' not in ready:
            _proc = None
            raise RuntimeError("Whisper не запустился")
    return _proc


def transcribe(audio: bytes, ctype: str) -> str:
    """Запись с микрофона (webm/ogg с Android и Chrome, mp4 с iPhone) → текст."""
    if not stt_available():
        raise RuntimeError("нет OpenJarvis с Whisper")
    ext = ".mp4" if "mp4" in ctype or "aac" in ctype else ".ogg" if "ogg" in ctype else ".webm"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio)
        path = f.name
    try:
        with _LOCK:  # один разговор за раз — модель общая
            p = _worker()
            p.stdin.write(json.dumps({"path": path}) + "\n")
            p.stdin.flush()
            res = json.loads(p.stdout.readline() or "{}")
    finally:
        Path(path).unlink(missing_ok=True)
    if "error" in res:
        raise RuntimeError(res["error"])
    return res.get("text", "")


# ---------------------------------------------- нейросетевой голос (Chatterbox, образец в data/voice)
VOICE_PY = Path.home() / ".jarvis-voice" / "bin" / "python"
REF_DIR = HERE / "data" / "voice"
TONE = {"exaggeration": 0.4, "cfg": 0.5}  # спокойный дворецкий: меньше эмоций, ровный темп
_TLOCK = threading.Lock()
_tproc: subprocess.Popen | None = None


# shortcut: на M1 Pro Chatterbox готовит 5 с речи ~55 с — для разговора слишком медленно, поэтому выключен;
# включить (True), когда будет Мак/видеокарта быстрее или модель шустрее.
NEURAL_ENABLED = False


def neural_available() -> bool:
    return NEURAL_ENABLED and VOICE_PY.exists() and (HERE / "tts_worker.py").exists()


def reference() -> str:
    """Образец голоса: data/voice/jarvis.wav (или .mp3/.m4a); нет — встроенный голос модели."""
    for name in ("jarvis.wav", "jarvis.mp3", "jarvis.m4a", "jarvis.flac"):
        if (REF_DIR / name).is_file():
            return str(REF_DIR / name)
    return ""


def _readline(proc: subprocess.Popen, timeout: float) -> str:
    import select
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    return proc.stdout.readline() if ready else ""


_TREADY = threading.Event()


def _tstart() -> None:
    """Запустить нейросеть в фоне: пока модель грузится (первый раз — скачивается), говорит Yuri."""
    global _tproc
    with _TLOCK:
        if _tproc is not None and _tproc.poll() is None:
            return
        _TREADY.clear()
        _tproc = subprocess.Popen([str(VOICE_PY), "-I", str(HERE / "tts_worker.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8")
        proc = _tproc

    def wait_ready():
        if '"ready"' in (proc.stdout.readline() or ""):
            _TREADY.set()
        else:
            proc.kill()

    threading.Thread(target=wait_ready, daemon=True).start()


def _tworker() -> subprocess.Popen:
    """Готовый процесс нейросети или исключение (тогда фраза — голосом Yuri)."""
    if _tproc is None or _tproc.poll() is not None:
        _tstart()
    if not _TREADY.is_set():
        raise RuntimeError("нейросетевой голос ещё загружается")
    return _tproc


def _neural(text: str, wav: Path) -> None:
    p = _tworker()
    with _TLOCK:
        p.stdin.write(json.dumps({"text": text, "out": str(wav), "ref": reference(), **TONE}, ensure_ascii=False) + "\n")
        p.stdin.flush()
        line = _readline(p, 60)
        if not line:  # завис — перезапустим в фоне, а сейчас скажет Yuri
            p.kill()
            _TREADY.clear()
            raise RuntimeError("нейросетевой голос не ответил")
        res = json.loads(line)
    if "error" in res:
        raise RuntimeError(res["error"])


# ------------------------------------------------- Piper: быстрый голос (0,2 с на фразу), без интернета
PIPER_DIR = Path.home() / ".jarvis-voice" / "voices"
PIPER_DEFAULT = "dmitri"
_PLOCK = threading.Lock()
_pproc: subprocess.Popen | None = None
_pvoice = ""


def piper_voice() -> str:
    """Какой голос Piper: имя из data/voice/голос.txt (denis, dmitri, ruslan), иначе по умолчанию."""
    try:
        name = (REF_DIR / "голос.txt").read_text(encoding="utf-8").strip().lower()
    except OSError:
        name = ""
    name = name or PIPER_DEFAULT
    return name if (PIPER_DIR / f"ru_RU-{name}-medium.onnx").is_file() else ""


def _piper(text: str, wav: Path) -> None:
    global _pproc, _pvoice
    name = piper_voice()
    if not (name and VOICE_PY.exists()):
        raise RuntimeError("Piper не установлен")
    with _PLOCK:
        if _pproc is None or _pproc.poll() is not None or _pvoice != name:  # сменили голос — перезапуск
            if _pproc is not None and _pproc.poll() is None:
                _pproc.kill()
            _pproc = subprocess.Popen([str(VOICE_PY), "-I", str(HERE / "piper_worker.py"),
                                       str(PIPER_DIR / f"ru_RU-{name}-medium.onnx")],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      text=True, encoding="utf-8")
            _pvoice = name
            if '"ready"' not in _readline(_pproc, 30):
                _pproc.kill()
                raise RuntimeError("Piper не запустился")
        _pproc.stdin.write(json.dumps({"text": text, "out": str(wav)}, ensure_ascii=False) + "\n")
        _pproc.stdin.flush()
        line = _readline(_pproc, 20)
        if not line:
            _pproc.kill()
            raise RuntimeError("Piper не ответил")
        res = json.loads(line)
    if "error" in res:
        raise RuntimeError(res["error"])


def tts(text: str) -> str:
    """Текст → m4a, base64. Piper (быстрый голос); нейросеть — если включена; запасной — Yuri этого Мака."""
    text = (text or "").strip()[:500]
    if not text:
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        src, m4a = Path(tmp) / "a.wav", Path(tmp) / "a.m4a"
        try:
            try:
                if neural_available():
                    _neural(text, src)
                else:
                    _piper(text, src)
            except Exception:  # noqa: BLE001 — запасной голос, чтобы Джарвис не замолкал
                src = Path(tmp) / "a.aiff"
                subprocess.run(["say", "-v", VOICE, "-o", str(src), "--", text], check=True, timeout=20,
                               capture_output=True)
            subprocess.run(["afconvert", "-f", "mp4f", "-d", "aac", str(src), str(m4a)], check=True,
                           timeout=20, capture_output=True)
            return base64.b64encode(m4a.read_bytes()).decode("ascii")
        except (OSError, subprocess.SubprocessError):
            return ""


# ------------------------------------------------- готовые фразы из звукового пакета (data/voice/клипы)
CLIP_DIR = REF_DIR / "клипы"
_CLIPS: dict[str, str] = {}  # имя → m4a base64 (конвертируем один раз и держим в памяти)


def clip_b64(name: str) -> str:
    """Фраза из пакета (настоящий голос Джарвиса из фильма) → m4a base64. Нет файла — пустая строка."""
    import re
    safe = re.sub(r"[^0-9a-zа-я_]", "", (name or "").lower())
    if not safe:
        return ""
    if safe in _CLIPS:
        return _CLIPS[safe]
    wav = CLIP_DIR / f"{safe}.wav"
    m4a = CLIP_DIR / f"{safe}.m4a"
    try:
        if not m4a.is_file():
            if not wav.is_file():
                return ""
            subprocess.run(["afconvert", "-f", "mp4f", "-d", "aac", str(wav), str(m4a)], check=True,
                           timeout=20, capture_output=True)
        _CLIPS[safe] = base64.b64encode(m4a.read_bytes()).decode("ascii")
        return _CLIPS[safe]
    except (OSError, subprocess.SubprocessError):
        return ""
