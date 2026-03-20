#!/bin/bash
#
# Push to GitHub
# 
# SETUP (do this once):
# 1. Create a new repository on GitHub: https://github.com/new
# 2. Do NOT initialize with README, .gitignore, or license
# 3. Copy the repository URL (HTTPS or SSH)
# 4. Run this script with the URL as argument:
#        bash push-to-github.sh https://github.com/yourusername/openclaw-crypto-agent.git
#

if [ -z "$1" ]; then
    echo "Usage: bash push-to-github.sh <github-repo-url>"
    echo ""
    echo "Example:"
    echo "  bash push-to-github.sh https://github.com/yourusername/openclaw-crypto-agent.git"
    echo ""
    echo "To create a new repo:"
    echo "  1. Go to https://github.com/new"
    echo "  2. Create repository named 'openclaw-crypto-agent'"
    echo "  3. Copy the HTTPS URL"
    echo "  4. Run this script with that URL"
    exit 1
fi

REPO_URL=$1

echo "=========================================="
echo "Pushing to GitHub"
echo "=========================================="
echo "Repository: $REPO_URL"
echo ""

# Add remote
echo "[1/3] Adding remote origin..."
git remote add origin "$REPO_URL"
git remote -v

echo ""
echo "[2/3] Pushing master branch..."
git push -u origin master

echo ""
echo "[3/3] Verification..."
git log --oneline -5

echo ""
echo "=========================================="
echo "✓ Successfully pushed to GitHub!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Visit: $REPO_URL"
echo "2. Clone from another machine:"
echo "   git clone $REPO_URL"
echo "   cd openclaw-crypto-agent"
echo "   bash setup.sh"
