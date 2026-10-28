#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"
command -v gh >/dev/null || { echo 'Instale o GitHub CLI (gh) primeiro.' >&2; exit 1; }
python tools/verificar-publicacao.py
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo 'Existem alterações não commitadas. Revise e faça commit antes de publicar.' >&2
  exit 1
fi
owner="$(gh api user --jq .login)"
repository="$owner/HitechDrive"
if git remote get-url origin >/dev/null 2>&1; then
  origin_url="$(git remote get-url origin)"
  case "$origin_url" in
    "https://github.com/$repository.git"|"https://github.com/$repository"|"git@github.com:$repository.git") ;;
    *) echo 'O origin aponta para outro destino. Publicação interrompida.' >&2; exit 1;;
  esac
  git push -u origin main
else
  if gh repo view "$repository" --json name >/dev/null 2>&1; then
    # Do not attach to or overwrite an existing repository automatically.
    echo "O repositório $repository já existe. Confira o destino antes de publicar." >&2
    exit 1
  fi
  gh repo create "$repository" --public --description 'Google Drive → Linux. Painel local, downloads retomáveis e controle de banda.' --source . --remote origin --push
fi
printf '\nPublicado em https://github.com/%s\n' "$repository"
