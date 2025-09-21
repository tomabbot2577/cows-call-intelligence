#!/bin/bash

# Git Push Script
# Pushes changes to GitHub repository

echo "========================================="
echo "📤 Pushing to GitHub Repository"
echo "========================================="
echo ""
echo "Repository: https://github.com/a9422crow/call-recording-system.git"
echo "Branch: main"
echo ""
echo "Latest commits:"
git log --oneline -5
echo ""
echo "========================================="
echo ""
echo "To push changes, you need to:"
echo ""
echo "1. Set up GitHub credentials:"
echo "   git config --global credential.helper store"
echo ""
echo "2. Then push with:"
echo "   git push origin main"
echo ""
echo "3. Enter your GitHub username and personal access token when prompted"
echo ""
echo "Or use the GitHub CLI:"
echo "   gh auth login"
echo "   git push origin main"
echo ""
echo "========================================="