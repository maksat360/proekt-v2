# -*- coding: utf-8 -*-
"""HTTPS в локальной сети: свой центр сертификации (ЦС) + сертификат сервера на адрес этого Мака.

Браузер даёт микрофон (голосовой Джарвис) только по https. ЦС создаётся один раз и ставится
на телефоны (страница /ca); сертификат сервера перевыпускается сам, если сменился IP в Wi-Fi.
Ключи лежат в data/tls (data/ не попадает в git).
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parent / "data" / "tls"
CA_KEY, CA_CRT = DIR / "ca.key", DIR / "ca.crt"
KEY, CRT, SAN_FILE = DIR / "server.key", DIR / "server.crt", DIR / "server.san"


def _openssl() -> str:
    for p in ("/opt/homebrew/bin/openssl", "/usr/local/bin/openssl", shutil.which("openssl") or ""):
        if p and Path(p).exists():
            return p
    raise RuntimeError("нет openssl")


def _run(*args: str) -> None:
    subprocess.run([_openssl(), *args], check=True, capture_output=True)


def san_for(ip: str) -> str:
    host = socket.gethostname().split(".")[0]
    names = ["DNS:localhost", f"DNS:{host}.local", "IP:127.0.0.1"] + ([f"IP:{ip}"] if ip else [])
    return ",".join(names)


def ensure(ip: str) -> tuple[Path, Path]:
    """Пути к сертификату и ключу сервера; при смене IP — перевыпуск (ЦС тот же, телефоны не трогаем)."""
    DIR.mkdir(parents=True, exist_ok=True)
    if not (CA_KEY.exists() and CA_CRT.exists()):
        _run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-sha256",
             "-keyout", str(CA_KEY), "-out", str(CA_CRT), "-subj", "/CN=Proekt V2 local CA",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        CA_KEY.chmod(0o600)
    san = san_for(ip)
    if KEY.exists() and CRT.exists() and SAN_FILE.exists() and SAN_FILE.read_text() == san:
        return CRT, KEY
    with tempfile.TemporaryDirectory() as tmp:
        csr, ext = Path(tmp) / "s.csr", Path(tmp) / "s.ext"
        ext.write_text("basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                       f"extendedKeyUsage=serverAuth\nsubjectAltName={san}\n")
        _run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(KEY), "-out", str(csr),
             "-subj", "/CN=Proekt V2")
        # 800 дней: iOS не доверяет сертификатам сервера дольше 825 дней
        _run("x509", "-req", "-in", str(csr), "-CA", str(CA_CRT), "-CAkey", str(CA_KEY),
             "-CAcreateserial", "-days", "800", "-sha256", "-extfile", str(ext), "-out", str(CRT))
    KEY.chmod(0o600)
    SAN_FILE.write_text(san)
    return CRT, KEY
