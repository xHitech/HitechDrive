#!/usr/bin/env bash
# Publish reviewed code, configure discoverability and create an experimental release.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"
command -v gh >/dev/null || { echo 'Instale o GitHub CLI (gh) primeiro.' >&2; exit 1; }
bash tools/publicar-github.sh
repository="$(gh api user --jq .login)/HitechDrive"
gh repo edit "$repository" \
  --description 'Google Drive → Linux. Visual dashboard, resumable downloads, bandwidth control and local recovery.' \
  --add-topic google-drive --add-topic linux --add-topic python --add-topic self-hosted \
  --add-topic sync --add-topic backup --add-topic jellyfin --enable-issues
release_tag='v0.1.0-alpha.1'
# A failed lookup is not assumed to mean absence: list must succeed first.
existing="$(gh release list --repo "$repository" --limit 100 --json tagName --jq '.[].tagName')"
if [[ $'\n'"$existing"$'\n' == *$'\n'"$release_tag"$'\n'* ]]; then
  echo 'A versão experimental já existe; ela não foi alterada.'
else
  gh release create "$release_tag" docs/demo.html docs/assets/social-preview.png --repo "$repository" --target "$(git rev-parse HEAD)" \
    --title 'HitechDrive v0.1.0-alpha.1 — Public preview' --prerelease \
    --notes-file docs/RELEASE-v0.1.0-alpha.1.md
fi
printf '\nPronto: https://github.com/%s\n' "$repository"
printf 'Capa social: envie docs/assets/social-preview.png em Settings > General > Social preview.\n'
