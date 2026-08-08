#!/bin/bash
cd "$(dirname "$0")"

echo "======================================="
echo "  Protein Lab — Protein Lab Manager"
echo "======================================="
echo ""
echo "  Installing dependencies..."
pip install -r requirements.txt -q

echo "  Starting server..."
echo "  Browser will open shortly → http://127.0.0.1:5000"
echo "  Close this window to stop the server."
echo ""

python app.py
