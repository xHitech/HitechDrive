#!/usr/bin/env bash
set -euo pipefail
if (( EUID == 0 )); then
    echo 'Execute como usuário normal, sem sudo.' >&2
    exit 1
fi
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$project_dir" == *'%'* || "$project_dir" == *'"'* || "$project_dir" == *$'\n'* ]]; then
    echo 'O caminho do projeto contém caracteres incompatíveis com esta instalação.' >&2
    exit 1
fi
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p -- "$unit_dir"
cat > "$unit_dir/drive-espelho.service" <<EOF
[Unit]
Description=Drive Espelho - Google Drive para RAID
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python "$project_dir/app.py"
Restart=on-failure
RestartSec=10
UMask=0022
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now drive-espelho.service
printf '\nDrive Espelho instalado. Abra: http://127.0.0.1:8765\n'
printf 'Inicia automaticamente com sua sessão de usuário.\n'
printf 'Para manter ativo após logout: sudo loginctl enable-linger "%s"\n' "$USER"
printf 'Logs: journalctl --user -u drive-espelho -f\n'
