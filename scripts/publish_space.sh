#!/usr/bin/env bash
# Publish this repository as a Hugging Face Docker Space.
#
#   HF_TOKEN=hf_xxx ./scripts/publish_space.sh <username>/<space-name>
#
# Builds a Space-shaped tree in a temporary directory: the repository as it is,
# with deploy/huggingface/README.md in place of the project README, because the
# Space reads its configuration from the README's front matter.
set -euo pipefail

SPACE="${1:?usage: publish_space.sh <username>/<space-name>}"
: "${HF_TOKEN:?set HF_TOKEN to a Hugging Face token with write access}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$ROOT" archive --format=tar HEAD | tar -x -C "$WORK"
cp "$WORK/deploy/huggingface/README.md" "$WORK/README.md"
rm -rf "$WORK/deploy"

cd "$WORK"
git init -q
git add -A
git -c user.email="$(git -C "$ROOT" config user.email)" \
    -c user.name="$(git -C "$ROOT" config user.name)" \
    commit -q -m "Deploy EvidenceFlow $(git -C "$ROOT" rev-parse --short HEAD)"
git push -q --force "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE}" HEAD:refs/heads/main

echo "pushed to https://huggingface.co/spaces/${SPACE}"
echo "the Space builds the Dockerfile and serves on app_port 8000; give it a few minutes"
