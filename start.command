#!/bin/bash
# Двойной клик — запуск портала «Проект V2». Откроется браузер с сайтом.
cd "$(dirname "$0")" || exit 1

URL="http://127.0.0.1:8787"
LAN=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
[ -n "$LAN" ] && LANURL="http://$LAN:8787" || LANURL="(нет Wi-Fi — подключи Mac к сети)"
[ -n "$LAN" ] && SECURL="https://$LAN:8443  (с голосом; сертификат: http://$LAN:8787/ca)" || SECURL=""

# Портал уже запущен в другом окне? Просто открываем браузер.
if curl -s -o /dev/null --max-time 1 "$URL"; then
  echo "Портал уже работает: $URL"
  echo "Для других устройств в Wi-Fi:  $LANURL"
  [ -n "$SECURL" ] && echo "С голосовым Джарвисом:  $SECURL"
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

# База PostgreSQL (склад, FBS) — поднимаем, если не запущена.
PGBIN=/opt/homebrew/opt/postgresql@17/bin
if [ -x "$PGBIN/pg_isready" ] && ! "$PGBIN/pg_isready" -q; then
  echo "Запускаю PostgreSQL…"
  brew services start postgresql@17 >/dev/null 2>&1
  for _ in 1 2 3 4 5 6 7 8 9 10; do "$PGBIN/pg_isready" -q && break; sleep 1; done
fi

if [ ! -f data/users.xlsx ]; then
  echo "Первый запуск — готовлю демо-данные…"
  $PY seed.py
fi


echo "Портал V2 запускается."
echo "С этого компьютера:  $URL"
echo "Для других устройств в Wi-Fi:  $LANURL"
[ -n "$SECURL" ] && echo "С голосовым Джарвисом:  $SECURL"
echo "Это окно закрывать нельзя — пока оно открыто, сайт работает."
echo "Остановить: Ctrl+C или просто закрой окно."
( sleep 1.5; open "$URL" ) &
exec $PY server.py --host 0.0.0.0
