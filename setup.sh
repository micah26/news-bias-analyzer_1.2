#!/bin/bash

echo "🚀 NewsLens Setup Script"
echo "========================"
echo ""

# Check Python version
echo "📍 Checking Python version..."
python3 --version

echo ""
echo "📦 Installing dependencies..."
pip install flask flask-sqlalchemy requests --break-system-packages

echo ""
echo "✅ Setup complete!"
echo ""
echo "To run the application:"
echo "  python app.py"
echo ""
echo "Then open: http://localhost:5000"
echo ""
echo "🎉 Enjoy NewsLens!"