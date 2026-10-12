#!/usr/bin/env bash
# Patch Microsoft Windows App (com.microsoft.rdc.androidx) so the RDP session
# draws under the display cutout instead of leaving a black band.
#
# Usage: ./patch.sh [--side-by-side] <official.apk> [output.apk]
#
# --side-by-side  install beside the official app: application id com.cyyself.windowsapp
#                 and label "Windows App Fullscreen" (override with PACKAGE_ID / APP_LABEL)
#
# Signing (defaults create/reuse work/patch.keystore):
#   KEYSTORE, KEYSTORE_PASS, KEY_ALIAS, KEY_PASS
# Tools: java, apktool (or APKTOOL_JAR), Android build-tools (ANDROID_HOME).
set -euo pipefail
cd "$(dirname "$0")"

PKG=com.microsoft.rdc.androidx
# SHA-256 of Microsoft's signing certificate for this app; rejects tampered inputs.
MS_CERT_SHA256=802477238a2158846843af80d7fc823d366caa3d0f26f96da4f8e22e85f1d2f5

if [ "${1:-}" = --side-by-side ]; then
  PACKAGE_ID=${PACKAGE_ID:-com.cyyself.windowsapp}
  APP_LABEL=${APP_LABEL:-Windows App Fullscreen}
  shift
fi
[ $# -ge 1 ] || { sed -n '5p' "$0"; exit 2; }
IN=$1

# --- tools ---------------------------------------------------------------
if ! java -version >/dev/null 2>&1 && command -v brew >/dev/null; then
  export JAVA_HOME=$(brew --prefix openjdk)/libexec/openjdk.jdk/Contents/Home
  export PATH=$JAVA_HOME/bin:$PATH
fi
SDK=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}
BT=${BUILD_TOOLS:-$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)}
if [ -n "${APKTOOL_JAR:-}" ]; then apktool() { java -jar "$APKTOOL_JAR" "$@"; }; fi

W=work; mkdir -p $W/out

# --- verify input --------------------------------------------------------
BADGING=$("$BT/aapt2" dump badging "$IN" | awk "NR==1")
[[ $BADGING == *"name='$PKG'"* ]] || { echo "error: $IN is not $PKG" >&2; exit 1; }
VERSION=$(sed -E "s/.*versionName='([^']*)'.*/\1/" <<<"$BADGING")
CERT=$("$BT/apksigner" verify --print-certs "$IN" 2>/dev/null | sed -nE 's/^Signer #1 certificate SHA-256 digest: //p; s/^V2 Signer: certificate SHA-256 digest: //p' | awk "NR==1")
if [ "$CERT" != "$MS_CERT_SHA256" ] && [ "${SKIP_CERT_CHECK:-}" != 1 ]; then
  echo "error: $IN is not signed by Microsoft (cert $CERT); refusing to patch. SKIP_CERT_CHECK=1 overrides." >&2
  exit 1
fi
VARIANT=nocutout; [ -n "${PACKAGE_ID:-}" ] && VARIANT=side-by-side
OUT=${2:-$W/out/WindowsApp-$VERSION-$VARIANT.apk}
echo "Patching $PKG $VERSION"

# --- patch ---------------------------------------------------------------
rm -rf $W/smali
apktool d -f -o $W/smali "$IN"
python3 -I scripts/patch_smali.py $W/smali ${PACKAGE_ID:+--package "$PACKAGE_ID"} ${APP_LABEL:+--label "$APP_LABEL"}
apktool b $W/smali -o $W/out/unsigned.apk

# --- sign ----------------------------------------------------------------
KEYSTORE=${KEYSTORE:-$W/patch.keystore}
KEYSTORE_PASS=${KEYSTORE_PASS:-android}
KEY_ALIAS=${KEY_ALIAS:-patch}
KEY_PASS=${KEY_PASS:-$KEYSTORE_PASS}
export KEYSTORE_PASS KEY_PASS
[ -f "$KEYSTORE" ] || keytool -genkeypair -keystore "$KEYSTORE" -storepass "$KEYSTORE_PASS" -keypass "$KEY_PASS" \
  -alias "$KEY_ALIAS" -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=RD Patch"
"$BT/zipalign" -f -p 4 $W/out/unsigned.apk $W/out/aligned.apk
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass env:KEYSTORE_PASS --ks-key-alias "$KEY_ALIAS" --key-pass env:KEY_PASS \
  --out "$OUT" $W/out/aligned.apk
rm -f $W/out/unsigned.apk $W/out/aligned.apk "$OUT.idsig"
echo "Built $OUT"
