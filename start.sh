#!/bin/bash
set -e

echo "🔍 SP Migration Companion — Local Dev Startup"
echo "=============================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi

echo "✓ Python $(python3 --version 2>&1 | awk '{print $2}')"

# Check if venv exists, create if not
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate
echo "✓ Virtual environment activated"

# Install/upgrade deps
echo ""
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt 2>/dev/null || {
    echo "❌ Failed to install requirements. Check requirements.txt"
    exit 1
}
echo "✓ Dependencies installed"

# Set HF_TOKEN if not already set
if [ -z "$HF_TOKEN" ]; then
    if [ -f ".env" ]; then
        echo "✓ Loading .env"
        set -a
        source .env
        set +a
    else
        echo ""
        echo "⚠️  HF_TOKEN not set. AI insights will be disabled."
        echo "   To enable: export HF_TOKEN=hf_your_token_here"
        echo "   Get free token: https://huggingface.co/settings/tokens"
    fi
fi

# Start FastAPI backend in background
echo ""
echo "🚀 Starting FastAPI backend on http://localhost:8000"
python3 main.py &
BACKEND_PID=$!
echo "   PID: $BACKEND_PID"

# Wait for backend to start
sleep 3

# Check if backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ Backend failed to start"
    exit 1
fi

echo "✓ Backend running"

# Open UI in browser
echo ""
echo "🌐 Opening UI in browser..."
if command -v open &> /dev/null; then
    # macOS
    open index.html
elif command -v xdg-open &> /dev/null; then
    # Linux
    xdg-open index.html
elif command -v start &> /dev/null; then
    # Windows
    start index.html
else
    echo "⚠️  Could not auto-open browser. Open index.html manually."
fi

echo ""
echo "=============================================="
echo "✅ SP Migration Companion is ready!"
echo ""
echo "   Frontend: file://$(pwd)/index.html"
echo "   Backend:  http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "⏸️  Press Ctrl+C to stop"
echo ""

# Wait for Ctrl+C
trap "echo ''; echo 'Shutting down...'; kill $BACKEND_PID; echo 'Done'; exit 0" SIGINT
wait $BACKEND_PID
