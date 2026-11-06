#!/bin/bash
# Сборка APK без Gradle: aapt2 → javac → d8 → zipalign → apksigner.
# Требуется: JDK 17 и Android SDK (build-tools 34, platform android-34).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK:-$HOME/.android-build/sdk}"
JDK="${JAVA_HOME:-$HOME/.android-build/jdk/Contents/Home}"
BT="$SDK/build-tools/34.0.0"
PLATFORM="$SDK/platforms/android-34/android.jar"
OUT="$HERE/build"
APK="$HERE/Проект-V2-цех.apk"

export JAVA_HOME="$JDK"
export PATH="$JDK/bin:$PATH"

for f in "$BT/aapt2" "$JDK/bin/javac" "$PLATFORM"; do
  [ -e "$f" ] || { echo "Не найдено: $f"; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/res" "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "→ встроенный интерфейс (assets/www)"
WWW="$OUT/assets/www"
mkdir -p "$WWW/icons"
SRC_STATIC="$HERE/../static"
cp "$SRC_STATIC/index.html" "$SRC_STATIC/sklad.html" "$SRC_STATIC/app.js" \
   "$SRC_STATIC/style.css" "$SRC_STATIC/sw.js" \
   "$SRC_STATIC/manifest.webmanifest" "$SRC_STATIC/manifest-sklad.webmanifest" "$WWW/" 2>/dev/null || true
cp "$SRC_STATIC/icons/"*.png "$WWW/icons/" 2>/dev/null || true
rm -f "$WWW/icons/"*1024.png
du -sh "$WWW" | awk '{print "   интерфейс: " $1}'

echo "→ ресурсы"
"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/res"

echo "→ манифест и ресурсы в APK"
FLATS=()
while IFS= read -r f; do FLATS+=("$f"); done < <(find "$OUT/res" -name '*.flat')
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLATFORM" \
  --manifest "$HERE/AndroidManifest.xml" \
  --java "$OUT/gen" \
  --min-sdk-version 24 --target-sdk-version 34 \
  --version-code 3 --version-name 3.0 -A "$OUT/assets" "${FLATS[@]}"

echo "→ компиляция Java"
: > "$OUT/sources.txt"
while IFS= read -r -d '' f; do printf '"%s"\n' "$f"; done \
  < <(find "$HERE/java" "$OUT/gen" -name '*.java' -print0) > "$OUT/sources.txt"
"$JDK/bin/javac" -source 8 -target 8 -encoding UTF-8 -nowarn \
  -bootclasspath "$PLATFORM" -d "$OUT/classes" @"$OUT/sources.txt"

echo "→ dex"
"$JDK/bin/jar" cf "$OUT/classes.jar" -C "$OUT/classes" .
"$BT/d8" --lib "$PLATFORM" --min-api 24 --output "$OUT/dex" "$OUT/classes.jar"

echo "→ упаковка"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
( cd "$OUT" && zip -q -j unsigned.apk dex/classes.dex )

if [ ! -f "$HERE/keystore.jks" ]; then
  echo "→ создаю ключ подписи (один раз)"
  "$JDK/bin/keytool" -genkeypair -v -keystore "$HERE/keystore.jks" -alias ceh \
    -keyalg RSA -keysize 2048 -validity 10000 -storepass ceh2026 -keypass ceh2026 \
    -dname "CN=Shveyny Ceh, OU=App, O=Project V2, L=Bishkek, C=KG" >/dev/null 2>&1
fi

"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
rm -f "$APK"
"$BT/apksigner" sign --ks "$HERE/keystore.jks" --ks-pass pass:ceh2026 \
  --key-pass pass:ceh2026 --out "$APK" "$OUT/aligned.apk"

echo "→ проверка подписи"
"$BT/apksigner" verify --print-certs "$APK" | head -4
"$BT/aapt2" dump badging "$APK" | head -5
echo "Готово: $APK"
