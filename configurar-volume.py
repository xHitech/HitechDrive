#!/usr/bin/env python3
"""Configure an existing mounted volume. Never mounts, formats or erases disks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from drive import load_json, save_json

def main():
    parser = argparse.ArgumentParser(description='Configurar o volume local do HitechDrive')
    parser.add_argument('--mountpoint', required=True, type=Path, help='Ponto de montagem de um volume já montado')
    parser.add_argument('--destination', type=Path, help='Subpasta que receberá a réplica; padrão: GoogleDrive no volume')
    parser.add_argument('--state', type=Path, default=Path.home()/'.local/share/drive-espelho')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Execute como seu usuário normal, sem sudo.')
    mountpoint=args.mountpoint.expanduser().resolve()
    destination=(args.destination.expanduser() if args.destination else mountpoint/'GoogleDrive').resolve()
    state=args.state.expanduser().resolve()
    if destination == mountpoint or not destination.is_relative_to(mountpoint):
        parser.error('O destino precisa ser uma subpasta do volume.')
    result=subprocess.run(['findmnt','--noheadings','--raw','--output','UUID','--mountpoint',str(mountpoint)],
                          capture_output=True,text=True,check=False)
    volume_uuid=result.stdout.strip()
    if result.returncode or not volume_uuid or len(volume_uuid.splitlines()) != 1:
        parser.error('O ponto informado precisa ser um volume montado com UUID identificável.')
    config=load_json(state/'config.json', {'paused':True})
    if not config.get('paused', True):
        parser.error('Pause a sincronização antes de configurar o volume.')
    instance={'mountpoint':str(mountpoint),'destination':str(destination),'volume_uuid':volume_uuid}
    previous=load_json(state/'instance.json')
    manifest=load_json(state/'manifest.json')
    if manifest.get('files') and previous != instance:
        parser.error('Já existe uma réplica registrada. A troca de volume foi bloqueada para preservar os dados.')
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(state,0o700)
    save_json(state/'instance.json',instance)
    print('Volume configurado. Reinicie o HitechDrive para carregar a configuração.')
    print('Nenhum disco foi montado ou formatado por este comando.')

if __name__=='__main__':
    main()
