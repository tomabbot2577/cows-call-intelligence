#!/bin/bash

# Push to GitHub Script
# This script helps push your changes to GitHub

echo "========================================="
echo "Git Push to GitHub"
echo "========================================="

# Check current branch
BRANCH=$(git branch --show-current)
echo "Current branch: $BRANCH"

# Show commits to be pushed
echo ""
echo "Commits to push:"
git log origin/$BRANCH..$BRANCH --oneline

echo ""
echo "========================================="
echo "GitHub Authentication Required"
echo "========================================="
echo ""
echo "You have 3 options to authenticate:"
echo ""
echo "Option 1: Personal Access Token (Recommended)"
echo "----------------------------------------"
echo "1. Go to: https://github.com/settings/tokens"
echo "2. Click 'Generate new token (classic)'"
echo "3. Give it a name like 'call-recording-system'"
echo "4. Select scopes: repo (all)"
echo "5. Generate token and copy it"
echo ""
echo "Then run:"
echo "git push https://YOUR_USERNAME:YOUR_TOKEN@github.com/a9422crow/call-recording-system.git main"
echo ""
echo "Option 2: GitHub CLI (gh)"
echo "----------------------------------------"
echo "# Install GitHub CLI"
echo "curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg"
echo "echo 'deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main' | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null"
echo "sudo apt update && sudo apt install gh -y"
echo ""
echo "# Authenticate"
echo "gh auth login"
echo ""
echo "# Push"
echo "gh repo sync"
echo ""
echo "Option 3: SSH Key"
echo "----------------------------------------"
echo "# Generate SSH key"
echo "ssh-keygen -t ed25519 -C 'your_email@example.com'"
echo ""
echo "# Add to GitHub: https://github.com/settings/keys"
echo "cat ~/.ssh/id_ed25519.pub"
echo ""
echo "# Change remote to SSH"
echo "git remote set-url origin git@github.com:a9422crow/call-recording-system.git"
echo ""
echo "# Push"
echo "git push origin main"
echo ""
echo "========================================="

# Try to push (will prompt for credentials)
read -p "Do you want to try pushing now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "Attempting to push..."
    echo "You'll be prompted for your GitHub username and password/token"
    git push origin $BRANCH
fi