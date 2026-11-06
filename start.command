#!/bin/bash
# Двойной клик — запуск портала «Проект V2». Откроется браузер с сайтом.
cd "$(dirname "$0")" || exit 1

URL="http://127.0.0.1:8787"

# Портал уже запущен в другом окне? Просто открываем браузер.
if curl -s -o /dev/null --max-time 1 "$URL"; then
  echo "Портал уже работает: $URL"
  open "$URL"
  exit 0
fi

PY=python3
if ! $PY -c "import openpyxl" >/dev/null 2>&1; then
  ALT="/Users/temp/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3"
  if [ -x "$ALT" ]; then
    PY="$ALT"
  else
    echo "В системе нет библиотеки openpyxl."
    echo "Выполни в терминале:  pip3 install openpyxl"
    read -n 1 -s -r -p "Нажми Enter, чтобы закрыть"
    exit 1
  fi
fi

if [ ! -f data/users.xlsx ]; then
  echo "Первый запуск — готовлю демо-данные…"
  $PY seed.py
fi

LAN=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

echo "Портал V2 запускается."
echo "С этого компьютера:  $URL"
if [ -n "$LAN" ]; then
  echo "С телефона в Wi-Fi:  http://$LAN:8787"
fi
echo "Это окно закрывать нельзя — пока оно открыто, сайт работает."
echo "Остановить: Ctrl+C или просто закрой окно."
( sleep 1.5; open "$URL" ) &
exec $PY server.py --host 0.0.0.0
