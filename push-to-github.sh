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

# Add or update remote
echo "[1/3] Configuring remote origin..."
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REPO_URL"
    echo "Updated existing origin URL"
else
    git remote add origin "$REPO_URL"
    echo "Added new origin URL"
fi
git remote -v

echo ""
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "[2/3] Pushing $CURRENT_BRANCH branch..."
if ! git push -u origin "$CURRENT_BRANCH"; then
    echo ""
    echo "❌ Push failed. Common reasons:"
    echo "  - Repository does not exist on GitHub yet"
    echo "  - Wrong owner/repo name in URL"
    echo "  - You do not have access to this repository"
    echo "  - Authentication token/login expired"
    echo ""
    echo "Fix:"
    echo "  1) Create repo at https://github.com/new"
    echo "  2) Use exact URL from GitHub"
    echo "  3) Re-run: bash push-to-github.sh <github-repo-url>"
    exit 1
fi

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
