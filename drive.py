"""Google Drive read-only REST client, OAuth desktop + PKCE, resumable downloads."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://www.googleapis.com/drive/v3/'
SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
FOLDER = 'application/vnd.google-apps.folder'
EXPORTS = {
 'application/vnd.google-apps.document': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'),
 'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
 'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
 'application/vnd.google-apps.drawing': ('application/pdf', '.pdf'),
}
FIELDS = 'id,name,mimeType,size,md5Checksum,modifiedTime,version,parents,webViewLink,trashed'

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {} if default is None else default

class AuthenticationRequired(RuntimeError):
    pass

class StorageUnavailable(RuntimeError):
    pass

class InsufficientSpace(RuntimeError):
    pass

class Paused(Exception):
    pass

class Drive:
    def __init__(self, state):
        self.state = Path(state)
        self.lock = threading.RLock()
        self.pending = None
        self.throttle = None
        self.observe = lambda stage, duration: None

    def credentials(self):
        value = load_json(self.state / 'client.json')
        c = value.get('installed', {})
        if not c.get('client_id') or not c.get('client_secret'):
            raise ValueError('Importe o JSON OAuth de aplicativo para computador do Google Cloud.')
        return c

    def authorize(self, redirect):
        self.credentials()
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        self.pending = (state, verifier, redirect, time.time())
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
            'client_id': self.credentials()['client_id'], 'redirect_uri': redirect,
            'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline',
            'prompt': 'consent', 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256'})

    def exchange(self, code, state):
        if not self.pending:
            raise ValueError('Autorização expirada. Conecte novamente.')
        expected, verifier, redirect, started = self.pending
        if not secrets.compare_digest(state, expected) or time.time() - started > 600:
            raise ValueError('Autorização inválida ou expirada.')
        self.pending = None
        tokens = self.token_request({'code': code, 'code_verifier': verifier,
                                    'redirect_uri': redirect, 'grant_type': 'authorization_code'})
        if not tokens.get('refresh_token'):
            raise ValueError('O Google não forneceu autorização offline; conecte novamente.')
        tokens['expires_at'] = time.time() + tokens.get('expires_in', 3600)
        save_json(self.state / 'tokens.json', tokens)

    def token_request(self, params):
        c = self.credentials()
        body = urllib.parse.urlencode(dict(params, client_id=c['client_id'], client_secret=c['client_secret'])).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=body), timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise AuthenticationRequired('A autorização do Google expirou ou foi recusada. Reconecte sua conta.') from e

    def token(self):
        with self.lock:
            tokens = load_json(self.state / 'tokens.json')
            if not tokens:
                raise ValueError('Conecte sua conta Google primeiro.')
            if tokens.get('expires_at', 0) < time.time() + 90:
                refreshed = self.token_request({'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token'})
                tokens.update(refreshed)
                tokens['expires_at'] = time.time() + refreshed.get('expires_in', 3600)
                save_json(self.state / 'tokens.json', tokens)
            return tokens['access_token']

    def request(self, endpoint, params=None, headers=None):
        url = API + endpoint + ('?' + urllib.parse.urlencode(params) if params else '')
        for attempt in range(5):
            started = time.monotonic()
            try:
                req = urllib.request.Request(url, headers=dict(headers or {}, Authorization='Bearer ' + self.token()))
                response = urllib.request.urlopen(req, timeout=60)
                self.observe('api', time.monotonic() - started)
                return response
            except urllib.error.HTTPError as e:
                self.observe('api', time.monotonic() - started)
                self.observe('api_error', 1)
                if e.code == 401 and attempt == 0:
                    with self.lock:
                        t = load_json(self.state / 'tokens.json'); t['expires_at'] = 0
                        save_json(self.state / 'tokens.json', t)
                    continue
                retry = e.code in (429, 500, 502, 503, 504)
                if e.code == 403:
                    retry = b'rateLimitExceeded' in e.read()
                if retry and attempt < 4:
                    time.sleep(min(2 ** attempt + secrets.randbelow(1000) / 1000, 30))
                    continue
                raise RuntimeError(f'Google Drive respondeu HTTP {e.code}; verifique permissões, API e cota.') from e
        raise RuntimeError('Google Drive indisponível.')

    def json(self, endpoint, params=None):
        with self.request(endpoint, params) as r:
            return json.load(r)

    def children(self, folder):
        token = None
        while True:
            safe_id = folder.replace('\\', '\\\\').replace("'", "\\'")
            params = {'q': f"'{safe_id}' in parents and trashed = false", 'spaces': 'drive',
                      'pageSize': 1000, 'fields': f'nextPageToken,incompleteSearch,files({FIELDS})'}
            if token:
                params['pageToken'] = token
            page = self.json('files', params)
            if page.get('incompleteSearch'):
                raise RuntimeError('O Google retornou uma listagem incompleta; nenhuma exclusão será aplicada.')
            yield from page.get('files', [])
            token = page.get('nextPageToken')
            if not token:
                break

    def catalog(self, check, progress):
        """Atomic metadata cache + change cursor; never commit a partial listing."""
        cache_path = self.state / 'catalog.json'
        cached = load_json(cache_path)
        items = dict(cached.get('items', {}))
        cursor = cached.get('cursor')
        for recovery in range(2):
            check()
            if not cursor:
                cursor = self.json('changes/startPageToken')['startPageToken']
                items = {}
                page_token = None
                while True:
                    check()
                    params = {'q': 'trashed = false', 'spaces': 'drive', 'corpora': 'user',
                              'pageSize': 1000, 'fields': f'nextPageToken,incompleteSearch,files({FIELDS})'}
                    if page_token:
                        params['pageToken'] = page_token
                    page = self.json('files', params)
                    if page.get('incompleteSearch'):
                        raise RuntimeError('Listagem incompleta do Google; catálogo anterior preservado.')
                    for item in page.get('files', []):
                        items[item['id']] = item
                    progress(f'{len(items)} itens catalogados no Google Drive')
                    page_token = page.get('nextPageToken')
                    if not page_token:
                        break
            # Include changes made while the full listing was in progress.
            try:
                changes = 0
                while True:
                    check()
                    page = self.json('changes', {'pageToken': cursor, 'pageSize': 1000,
                        'spaces': 'drive', 'includeRemoved': 'true',
                        'fields': f'nextPageToken,newStartPageToken,changes(fileId,removed,file({FIELDS}))'})
                    for change in page.get('changes', []):
                        fid = change['fileId']
                        item = change.get('file')
                        if change.get('removed') or (item and item.get('trashed')):
                            items.pop(fid, None)
                        elif item:
                            items[fid] = item
                        else:
                            raise RuntimeError('Alteração sem metadados; catálogo anterior preservado.')
                        changes += 1
                    progress(f'{changes} alterações consultadas; {len(items)} itens no catálogo')
                    next_page = page.get('nextPageToken')
                    if next_page:
                        cursor = next_page
                    else:
                        cursor = page.get('newStartPageToken')
                        if not cursor:
                            raise RuntimeError('Google não retornou o cursor de alterações; catálogo anterior preservado.')
                        break
            except RuntimeError as exc:
                if getattr(exc.__cause__, 'code', None) == 410 and recovery == 0:
                    cursor = None
                    progress('Histórico expirado; reconstruindo catálogo')
                    continue
                raise
            check()
            save_json(cache_path, {'cursor': cursor, 'items': items})
            return items
        raise RuntimeError('Não foi possível atualizar o catálogo do Drive.')

    def download(self, item, part, progress, check):
        """Caller keys .part by file ID + version, so old versions cannot be appended."""
        export = EXPORTS.get(item['mimeType'])
        endpoint = 'files/' + urllib.parse.quote(item['id'], safe='')
        params = {'alt': 'media'}
        if export:
            endpoint += '/export'; params = {'mimeType': export[0]}
        offset = part.stat().st_size if part.exists() and not export else 0
        total = int(item.get('size', 0)) if not export else 0
        if offset and total and offset > total:
            part.unlink(); offset = 0
        if not (offset and total and offset == total):
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with self.request(endpoint, params, headers) as r:
                if offset and r.status == 206:
                    if not r.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                        raise RuntimeError('Resposta parcial inválida; download preservado para nova tentativa.')
                elif offset:
                    offset = 0  # Server ignored Range: restart rather than append.
                if not total:
                    total = int(r.headers.get('Content-Length', 0)) + offset
                done = offset
                length = r.headers.get('Content-Length')
                remaining = int(length) if length is not None else None
                with part.open('ab' if offset else 'wb') as out:
                    while True:
                        check()
                        if remaining is not None and remaining <= 0:
                            break
                        amount = min(256 * 1024, remaining) if remaining is not None else 256 * 1024
                        if self.throttle:
                            started = time.monotonic()
                            self.throttle(amount, check)
                            self.observe('throttle', time.monotonic() - started)
                        started = time.monotonic()
                        try:
                            chunk = r.read(amount)
                        finally:
                            self.observe('receive', time.monotonic() - started)
                        if not chunk:
                            break
                        if remaining is not None:
                            remaining -= len(chunk)
                        started = time.monotonic()
                        try:
                            out.write(chunk)
                        finally:
                            self.observe('write', time.monotonic() - started)
                        done += len(chunk)
                        progress(done, total)
                    if remaining is not None and remaining > 0:
                        raise RuntimeError('Transferência incompleta: o Google encerrou a resposta antes do tamanho anunciado.')
                    started = time.monotonic()
                    out.flush(); os.fsync(out.fileno())
                    self.observe('write', time.monotonic() - started)
        check()
        if not export and 'size' in item and part.stat().st_size != int(item['size']):
            raise RuntimeError('Download incompleto; será retomado no próximo ciclo.')
        started = time.monotonic()
        md5 = hashlib.md5()
        with part.open('rb') as stream:
            while chunk := stream.read(4 * 1024 * 1024):
                check(); md5.update(chunk)
        self.observe('verify', time.monotonic() - started)
        if not export and item.get('md5Checksum') and md5.hexdigest() != item['md5Checksum']:
            part.unlink()
            raise RuntimeError('Checksum divergente; arquivo será baixado novamente.')
        # Recheck metadata after transfer to detect content modified during download.
        latest = self.json('files/' + urllib.parse.quote(item['id'], safe=''),
                           {'fields': 'version,trashed'})
        if latest.get('trashed') or latest.get('version') != item.get('version'):
            part.unlink()
            raise RuntimeError('Arquivo mudou durante o download; será relido no próximo ciclo.')
        return md5.hexdigest()
