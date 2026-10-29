#!/usr/bin/env python3
"""Local dashboard for Drive Espelho. No remote access, no third-party packages."""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import urllib.parse

from drive import load_json, save_json
from engine import Engine
BASE = Path(__file__).resolve().parent

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # OAuth authorization codes must never enter access logs.

    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def reply(self, code, data, kind='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if kind.startswith('application/json') else data
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Host recusado.'})
        path = urllib.parse.urlsplit(self.path)
        engine = self.server.engine
        if path.path == '/api/diagnostics':
            return self.reply(200, engine.diagnostics.snapshot())
        if path.path == '/api/status':
            return self.reply(200, dict(engine.snapshot(), csrf=self.server.csrf))
        if path.path == '/oauth/callback':
            exchanged = False
            try:
                if not engine.config['paused'] or engine.maintenance.snapshot()['state'] == 'running':
                    raise ValueError('Pause a sincronização antes de conectar a conta.')
                query = urllib.parse.parse_qs(path.query)
                if 'error' in query:
                    raise ValueError('Autorização cancelada no Google.')
                with self.server.auth_lock:
                    engine.drive.exchange(query.get('code', [''])[0], query.get('state', [''])[0])
                    exchanged = True
                    account = engine.drive.json('about', {'fields': 'user(displayName,emailAddress,permissionId)'})['user']
                    pinned = load_json(engine.state / 'account.json')
                    if pinned and account['permissionId'] != pinned.get('permissionId'):
                        (engine.state / 'tokens.json').unlink(missing_ok=True)
                        raise ValueError('Esta réplica pertence a outra conta. A troca foi bloqueada para preservar os arquivos.')
                    save_json(engine.state / 'account.json', account)
                engine.clear_auth_error()
                engine.event('Conta Google conectada com permissão somente de leitura.')
                self.send_response(303); self.send_header('Location', '/'); self.end_headers()
                return
            except Exception as e:
                if exchanged:
                    (engine.state / 'tokens.json').unlink(missing_ok=True)
                engine.event(str(e))
                # No OAuth code or token is echoed into the page.
                return self.reply(400, str(e).encode(), 'text/plain; charset=utf-8')
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/ui.js': ('ui.js', 'text/javascript; charset=utf-8'),
                  '/theme.js': ('theme.js', 'text/javascript; charset=utf-8'),
                  '/maintenance.js': ('maintenance.js', 'text/javascript; charset=utf-8'),
                  '/diagnostics.js': ('diagnostics.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path.path in assets:
            name, kind = assets[path.path]
            return self.reply(200, (BASE / 'static' / name).read_bytes(), kind)
        self.reply(404, {'error': 'Não encontrado.'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed = (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
        if not self.valid_host() or (origin and origin not in allowed) or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), self.server.csrf):
            return self.reply(403, {'error': 'Requisição não autorizada.'})
        try:
            size = int(self.headers.get('Content-Length', 0))
            maximum = 32*1024*1024 if self.path == '/api/recovery-import' else 65536
            if not 0 < size <= maximum:
                raise ValueError('Requisição inválida ou muito grande.')
            body = json.loads(self.rfile.read(size))
            e = self.server.engine
            if self.path in ('/api/client','/api/connect','/api/settings') and e.maintenance.snapshot()['state'] == 'running':
                raise ValueError('Aguarde ou cancele a manutenção antes de alterar a conta ou configuração.')
            if self.path == '/api/client':
                if not e.config['paused'] or e.snapshot()['phase'] not in ('pausado', 'erro', 'aguardando'):
                    raise ValueError('Pause e espere o download atual parar primeiro.')
                c = body.get('installed', {})
                if not c.get('client_id', '').endswith('.apps.googleusercontent.com') or not c.get('client_secret'):
                    raise ValueError('Selecione o JSON de um cliente OAuth do tipo Aplicativo para computador.')
                save_json(e.state / 'client.json', {'installed': c})
                (e.state / 'tokens.json').unlink(missing_ok=True)
            elif self.path == '/api/connect':
                if not e.config['paused'] or e.snapshot()['phase'] not in ('pausado', 'erro', 'aguardando'):
                    raise ValueError('Pause e espere o download atual parar antes de conectar.')
                with self.server.auth_lock:
                    url = e.drive.authorize(f'http://127.0.0.1:{self.server.server_port}/oauth/callback')
                return self.reply(200, {'url': url})
            elif self.path == '/api/settings':
                root = body.get('root', 'root').strip() or 'root'
                if 'drive.google.com' in root:
                    parsed = urllib.parse.urlsplit(root)
                    if '/folders/' not in parsed.path:
                        raise ValueError('Use um link de pasta do Google Drive.')
                    root = parsed.path.split('/folders/', 1)[1].split('/')[0]
                e.settings(root, body.get('interval', 300), body.get('workers'))
            elif self.path == '/api/start':
                with self.server.auth_lock:
                    if e.auth_error or not (e.state / 'tokens.json').exists() or not (e.state / 'account.json').exists():
                        raise ValueError('Conecte sua conta Google primeiro.')
                    e.pause(False)
            elif self.path == '/api/retry-errors':
                if e.auth_error or not (e.state / 'tokens.json').exists() or not (e.state / 'account.json').exists():
                    raise ValueError('Conecte sua conta Google primeiro.')
                e.retry_errors()
            elif self.path == '/api/recovery-export':
                return self.reply(200, e.maintenance.export())
            elif self.path == '/api/recovery-checkpoint-import':
                e.maintenance.restore_checkpoint()
            elif self.path == '/api/recovery-import':
                e.maintenance.restore(body)
            elif self.path == '/api/maintenance-start':
                if body.get('kind') == 'rebuild' and (e.auth_error or not (e.state/'tokens.json').exists()):
                    raise ValueError('Conecte sua conta Google antes de reconstruir o índice.')
                e.maintenance.start(body.get('kind'), body.get('rate_mib',8))
            elif self.path == '/api/maintenance-cancel':
                e.maintenance.cancelled.set()
            elif self.path == '/api/cleanup-preview':
                return self.reply(200, e.maintenance.cleanup_preview())
            elif self.path == '/api/cleanup-confirm':
                return self.reply(200, e.maintenance.cleanup(body.get('token'),body.get('kind'),body.get('confirmation')))
            elif self.path == '/api/diagnostics-settings':
                e.set_internet_speed(body.get('internet_mbps'))
            elif self.path == '/api/workers':
                e.set_workers(body.get('workers'))
            elif self.path == '/api/bandwidth':
                e.set_bandwidth(body.get('bandwidth_mib'))
            elif self.path == '/api/pause':
                e.pause(True)
            else:
                return self.reply(404, {'error': 'Não encontrado.'})
            self.reply(200, {'ok': True})
        except Exception as exc:
            self.reply(400, {'error': str(exc)})

def main():
    parser = argparse.ArgumentParser(description='Drive Espelho — Google Drive → RAID')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/share/drive-espelho')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Execute como usuário normal, sem sudo.')
    os.umask(0o022)  # Media readable by Jellyfin; credential files explicitly use 0600.
    args.state = args.state.expanduser().resolve()
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (args.state / 'instance.lock').open('w')
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('O Drive Espelho já está rodando.')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.engine = Engine(args.state)
    server.csrf = secrets.token_urlsafe(32)
    server.auth_lock = threading.Lock()
    server.engine.start()
    print(f'Drive Espelho disponível em http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.engine.pause(True)
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
