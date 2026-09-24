#!/bin/bash
# Chay TTS Clone Studio tu ma nguon tren macOS (nhay dup file nay).
# Nguoi dung thuong nen tai ban .zip trong muc Releases tren GitHub thay vi dung file nay.
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.12 python3.13 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Khong tim thay Python 3.10+. Hay cai tu https://www.python.org/downloads/macos/"
  read -r -p "Nhan Enter de dong..." _
  exit 1
fi
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  rm -rf .venv
  "$PY" -m venv .venv || exit 1
fi
if ! .venv/bin/python -c 'import PyQt6.QtWidgets, imageio_ffmpeg' >/dev/null 2>&1; then
  echo "Dang cai thu vien (lan dau mat 1-3 phut)..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || { read -r -p "Cai loi. Nhan Enter..." _; exit 1; }
fi
exec .venv/bin/python launcher.py
