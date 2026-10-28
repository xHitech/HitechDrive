#!/usr/bin/env python3
"""Check tracked publication candidates without printing matching secret values."""
from pathlib import Path
import re
import subprocess
import sys

root=Path(__file__).resolve().parent.parent
tracked=subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0')
forbidden_names={'instance.json','config.json','account.json','manifest.json','catalog.json','errors.json','tokens.json','client.json','PLANO_DE_POLIMENTO.md'}
patterns={
 'chave privada':r'-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----',
 'token GitHub':r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
 'token Google':r'\bya29\.[A-Za-z0-9_-]{15,}',
 'segredo OAuth Google':r'\bGOCSPX-[A-Za-z0-9_-]{15,}',
 'chave API Google':r'\bAIza[A-Za-z0-9_-]{25,}',
 'UUID de volume':r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b',
 'diretório pessoal absoluto':r'/home/[A-Za-z0-9_.-]+/',
 'IP privado ou Tailscale':r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b',
}
issues=[]
for relative in filter(None,tracked):
 path=root/relative
 if path.name in forbidden_names or path.suffix in ('.pem','.key','.log','.part','.pyc') or 'client_secret' in path.name:
  issues.append((relative,'arquivo privado'))
 if path.is_symlink():
  issues.append((relative,'link simbólico não permitido na publicação'));continue
 try:content=path.read_text()
 except (UnicodeError,OSError):
  issues.append((relative,'arquivo ausente ou binário sem revisão'));continue
 for label,pattern in patterns.items():
  if re.search(pattern,content):issues.append((relative,label))
if issues:
 for path,label in issues:print(f'BLOQUEADO: {path}: {label}')
 sys.exit(1)
print(f'Verificação concluída: {len(list(filter(None,tracked)))} arquivos rastreados; nenhum padrão privado encontrado.')
print('A verificação por padrões complementa a revisão manual; não é garantia absoluta de ausência de segredos.')
