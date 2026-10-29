#!/usr/bin/env python3
"""Build a self-contained, offline demo from the actual UI and synthetic fixtures."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def build():
    static = ROOT / 'static'
    html = (static/'index.html').read_text()
    html = html.replace('<title>HitechDrive</title>', '<title>HitechDrive · offline demo</title>')
    html = html.replace('<body>', '<body><div style="padding:10px;text-align:center;background:#5B21B6;color:white;font:14px system-ui;position:relative;z-index:20">OFFLINE DEMO · Dados fictícios / Sample data · Não conecta contas nem acessa arquivos reais.</div>')
    html = html.replace('<script src="/theme.js"></script>', '<script>'+(static/'theme.js').read_text()+'</script>')
    html = html.replace('<link rel="stylesheet" href="/style.css">', '<style>'+(static/'style.css').read_text()+'</style>')
    for name in ('ui', 'diagnostics', 'maintenance'):
        html = html.replace(f'<script src="/{name}.js" defer></script>', '')
    mock = (ROOT/'tools/demo-fixture.js').read_text()
    scripts = mock + '\n' + '\n'.join((static/(name+'.js')).read_text() for name in ('ui','diagnostics','maintenance'))
    result = html.replace('</body>', '<script>'+scripts+'</script></body>')
    return '\n'.join(line.rstrip() for line in result.splitlines()) + '\n'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/demo.html')
    args = parser.parse_args()
    args.output.write_text(build())
    print('Offline demo generated from public UI assets and synthetic data.')
