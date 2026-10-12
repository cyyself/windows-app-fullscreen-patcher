#!/usr/bin/env bash
# Download the latest official Windows App APK into <outdir> and print its path.
# The source used ("Google Play" or "APKPure") is written to <outdir>/source.
#
# Google Play (preferred): set GP_EMAIL and GP_AAS_TOKEN.
# APKPure fallback: set ALLOW_APKPURE=1. Used when Play credentials are absent or the
# Play download fails; patch.sh still rejects anything not signed by Microsoft.
set -uo pipefail
PKG=com.microsoft.rdc.androidx
OUT=${1:?usage: download.sh <outdir>}
mkdir -p "$OUT"

# Prints the single APK in $1, or fails. apkeep's exit status alone isn't trusted.
single_apk() {
  local apks=("$1"/*.apk)
  if [ ${#apks[@]} -eq 1 ] && [ -f "${apks[0]}" ]; then echo "${apks[0]}"; return 0; fi
  echo "warning: expected one APK in $1, got: $(ls "$1" 2>/dev/null | tr '\n' ' ')" >&2
  return 1
}

if [ -n "${GP_EMAIL:-}" ] && [ -n "${GP_AAS_TOKEN:-}" ]; then
  echo "Downloading $PKG from Google Play" >&2
  mkdir -p "$OUT/google-play"
  apkeep -a $PKG -d google-play -e "$GP_EMAIL" -t "$GP_AAS_TOKEN" --accept-tos \
    ${GP_DEVICE:+-o device=$GP_DEVICE} "$OUT/google-play" >&2 || echo "warning: apkeep (Google Play) failed" >&2
  if apk=$(single_apk "$OUT/google-play"); then
    echo "Google Play" > "$OUT/source"; echo "$apk"; exit 0
  fi
  echo "warning: Google Play download failed" >&2
else
  echo "No Google Play credentials set" >&2
fi

if [ "${ALLOW_APKPURE:-}" != 1 ]; then
  echo "error: no APK downloaded; set GP_EMAIL + GP_AAS_TOKEN, or ALLOW_APKPURE=1 to fall back to APKPure" >&2
  exit 1
fi

echo "Falling back to APKPure" >&2
mkdir -p "$OUT/apkpure"
apkeep -a $PKG -d apk-pure -o acknowledge_dangers=true,arch=arm64-v8a "$OUT/apkpure" >&2 || echo "warning: apkeep (APKPure) failed" >&2
apk=$(single_apk "$OUT/apkpure") || { echo "error: APKPure download failed" >&2; exit 1; }
echo "APKPure" > "$OUT/source"
echo "$apk"
