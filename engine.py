"""One-way mirror; complete scans, verified downloads, recoverable local trash."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import deque
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.parse

from maintenance import Maintenance
import relocations
from diagnostics import Diagnostics
from bandwidth import BandwidthLimiter
from drive import Drive, EXPORTS, FOLDER, Paused, AuthenticationRequired, StorageUnavailable, InsufficientSpace, load_json, save_json
DEST = Path('/srv/media/GoogleDrive')
RESERVED = '.drive-espelho'

def component(name):
    result = ''.join(f'%{ord(c):02X}' if c in '%/\\' or ord(c) < 32 else c for c in name)
    if result in ('', '.', '..') or result.startswith(RESERVED):
        result = '_' + result
    if len(result.encode()) > 180:
        suffix = hashlib.sha256(result.encode()).hexdigest()[:12]
        result = result.encode()[:150].decode('utf-8', 'ignore') + '~' + suffix
    return result

def filename(item):
    extension = EXPORTS.get(item['mimeType'], ('', ''))[1]
    if item['mimeType'].startswith('application/vnd.google-apps.') and not extension:
        extension = '.url'
    return component(item['name'] + extension)

def fingerprint(item):
    return '|'.join(str(item.get(x, '')) for x in ('version', 'modifiedTime', 'md5Checksum', 'size', 'mimeType'))

class Engine:
    def __init__(self, state, destination=None, guard=None):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state, 0o700)
        pending = load_json(self.state / 'recovery.pending.json')
        if pending:
            if set(pending) != {'account.json', 'config.json', 'manifest.json'}:
                raise RuntimeError('Diário de recuperação inválido; preserve os arquivos de estado para revisão.')
            for name, content in pending.items(): save_json(self.state / name, content)
            (self.state / 'recovery.pending.json').unlink()
        instance = load_json(self.state / 'instance.json')
        self.mountpoint = Path(instance.get('mountpoint', '/srv/media')).expanduser()
        self.expected_uuid = instance.get('volume_uuid', '')
        self.destination = Path(destination if destination is not None else instance.get('destination', str(DEST))).expanduser()
        self.drive = Drive(self.state)
        self.config = load_json(self.state / 'config.json', {'root': 'root', 'interval': 300, 'paused': True})
        self.config.setdefault('workers', 4)
        self.config.setdefault('bandwidth_mib', 0)
        self.bandwidth = BandwidthLimiter(self.config['bandwidth_mib'])
        self.drive.throttle = self.bandwidth.acquire
        self.active = {}
        self.reserved_bytes = 0
        self.manifest = load_json(self.state / 'manifest.json', {'files': {}, 'folders': []})
        self.guard = guard or self.mount_guard
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.status = {'phase': 'pausado' if self.config['paused'] else 'aguardando',
                       'current': '', 'done': 0, 'total': 0, 'bytes': 0, 'size': 0,
                       'speed': 0, 'last_sync': self.manifest.get('last_sync'), 'error': '', 'events': []}
        self.failures = load_json(self.state / 'errors.json')
        self.byte_plan = {}
        self.byte_positions = {}
        self.network_bytes = 0
        self.rate_samples = deque()
        self.config.setdefault('internet_mbps', 0)
        self.diagnostics = Diagnostics(self.diagnostic_context)
        self.drive.observe = self.diagnostics.observe
        self.operation_lock = threading.Lock()
        self.maintenance = Maintenance(self)
        self.auth_error = load_json(self.state/'auth-status.json').get('error', '')
        self.alert_cache = (0, [])
        self.thread = None

    def diagnostic_context(self):
        with self.lock:
            return {'network_bytes':self.network_bytes, 'bandwidth_mib':self.config['bandwidth_mib'],
                    'internet_mbps':self.config.get('internet_mbps',0)}

    def set_internet_speed(self, value):
        value=float(value)
        if not math.isfinite(value) or not 0 <= value <= 1000000:
            raise ValueError('Informe a velocidade do plano em Mbps, ou 0 se desconhecida.')
        with self.lock:
            updated=dict(self.config,internet_mbps=value)
            save_json(self.state/'config.json',updated)
            self.config.update(updated)

    def mount_guard(self):
        if not self.expected_uuid:
            raise StorageUnavailable('Configure o volume de destino com configurar-volume.py antes de sincronizar.')
        if not self.destination.is_absolute() or not self.mountpoint.is_absolute():
            raise RuntimeError('O volume e o destino precisam usar caminhos absolutos.')
        if not self.destination.resolve().is_relative_to(self.mountpoint.resolve()) or self.destination.resolve() == self.mountpoint.resolve():
            raise RuntimeError('O destino precisa ser uma subpasta do volume configurado.')
        probe = subprocess.run(['findmnt', '--noheadings', '--raw', '--output', 'UUID', '--mountpoint', str(self.mountpoint)],
                               capture_output=True, text=True)
        if probe.returncode or probe.stdout.strip() != self.expected_uuid:
            raise StorageUnavailable('O volume esperado não está montado no destino configurado. Sincronização bloqueada.')
        if self.mountpoint.is_symlink():
            raise RuntimeError('O ponto de montagem não pode ser um link simbólico.')

    def check(self):
        if self.config['paused']:
            raise Paused()

    def local(self, relative):
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or any(p in ('.', '..') for p in parts):
            raise RuntimeError('Caminho local inválido.')
        path = self.destination
        if path.is_symlink():
            raise RuntimeError('O destino não pode ser link simbólico.')
        for p in parts:
            path /= p
            if path.is_symlink():
                raise RuntimeError(f'Link simbólico encontrado: {path}; operação interrompida.')
        return path

    def event(self, text):
        with self.lock:
            self.status['events'] = ([{'time': time.strftime('%H:%M:%S'), 'text': text}]
                                     + self.status['events'])[:40]

    def persist(self):
        with self.lock:
            save_json(self.state / 'manifest.json', self.manifest)

    def settings(self, root, interval, workers=None):
        with self.lock:
            if self.maintenance.snapshot()['state'] == 'running':
                raise ValueError('Aguarde a manutenção terminar antes de alterar a configuração.')
            if not self.config['paused'] or (self.thread and self.status['phase'] not in ('pausado', 'erro', 'aguardando')):
                raise ValueError('Pause e espere a operação atual terminar antes de alterar a configuração.')
            if self.manifest['files'] and root != self.config['root']:
                raise ValueError('A origem já tem arquivos sincronizados. Esta versão não troca a origem para evitar exclusões acidentais.')
            if not root or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in root):
                raise ValueError('Informe root ou o ID da pasta do Drive.')
            count = self.validate_workers(self.config.get('workers', 4) if workers is None else workers)
            self.config.update(root=root, interval=max(60, min(int(interval), 86400)), workers=count)
            save_json(self.state / 'config.json', self.config)

    @staticmethod
    def validate_workers(value):
        try:
            count = int(value)
            if isinstance(value, bool) or float(value) != count or not 1 <= count <= 8:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Escolha um número inteiro entre 1 e 8 downloads simultâneos.') from None
        return count

    def set_workers(self, value):
        count = self.validate_workers(value)
        with self.lock:
            updated = dict(self.config, workers=count)
            save_json(self.state / 'config.json', updated)
            self.config.update(updated)
            active = len(self.active)
        self.event(f'Limite de downloads simultâneos: {count}.' +
                   (f' {active} já iniciados vão terminar; novas vagas aguardam o limite.' if active > count else ''))

    def set_bandwidth(self, value):
        value = self.bandwidth.validate(value)
        with self.lock:
            updated = dict(self.config, bandwidth_mib=value)
            save_json(self.state / 'config.json', updated)
            self.config.update(updated)
            self.bandwidth.set_limit(value)
        self.event(f'Limite total de download: {value:g} MiB/s' if value else 'Download sem limite de velocidade.')

    def pause(self, paused):
        if not paused and self.maintenance.snapshot()['state'] == 'running':
            raise ValueError('Aguarde ou cancele a manutenção antes de retomar a sincronização.')
        with self.lock:
            self.config['paused'] = paused
            save_json(self.state / 'config.json', self.config)
            self.wake.set()

    def scan(self, check=None):
        """Never infer deletion from an interrupted/failed listing."""
        checker = check or self.check
        root = self.config['root']
        metadata = self.drive.json('files/' + urllib.parse.quote(root, safe=''), {'fields': 'id,mimeType,trashed'})
        if metadata.get('mimeType') != FOLDER or metadata.get('trashed'):
            raise RuntimeError('A pasta de origem não está disponível.')
        def progress(message):
            with self.lock:
                self.status['current'] = message
        catalog = self.drive.catalog(checker, progress)
        by_parent = {}
        for item in catalog.values():
            for parent in item.get('parents', []):
                by_parent.setdefault(parent, []).append(item)
        files, folders, seen = {}, [], set()
        stack = [(metadata['id'], '')]
        while stack:
            checker()
            parent, path = stack.pop()
            if parent in seen:
                raise RuntimeError('Estrutura cíclica de pastas; sincronização interrompida.')
            seen.add(parent)
            children = by_parent.get(parent, [])
            occupied = set()
            for child in sorted(children, key=lambda x: x['id']):
                checker()
                if child['mimeType'] == FOLDER:
                    name = component(child['name'])
                else:
                    name = filename(child)
                if name in occupied:
                    name += '~' + child['id']
                while name in occupied:
                    name += '_'
                occupied.add(name)
                relative = path + '/' + name if path else name
                if child['mimeType'] == FOLDER:
                    folders.append(relative); stack.append((child['id'], relative))
                else:
                    files[child['id']] = dict(child, relative=relative)
            with self.lock:
                self.status.update(total=len(files), current=f'{len(seen)} pastas verificadas')
        return files, folders

    def archive(self, path, reason):
        if not path.exists():
            return
        self.guard()
        relative = path.relative_to(self.destination)
        bucket = str(time.time_ns()) + '-' + reason
        trash = self.local(RESERVED + '/lixeira/' + bucket + '/' + str(relative))
        trash.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, trash)
        self.event(f'Guardado na lixeira local: {relative}')

    def same_local(self, path, entry):
        if not path.is_file():
            return False
        stat = path.stat()
        return stat.st_size == entry.get('size') and stat.st_mtime_ns == entry.get('mtime_ns')

    def prepare_progress(self, files):
        """Only metadata/stat calls: never re-read completed media to estimate progress."""
        planned, positions = {}, {}
        unknown = 0
        for fid, item in files.items():
            self.check()
            if item['mimeType'].startswith('application/vnd.google-apps.') or 'size' not in item:
                unknown += 1
                continue
            size = int(item['size'])
            planned[fid] = size
            entry = self.manifest['files'].get(fid, {})
            if entry.get('fingerprint') == fingerprint(item) and entry.get('path') == item['relative'] and self.same_local(self.local(item['relative']), entry):
                positions[fid] = size
            else:
                key = hashlib.sha256((fid + fingerprint(item)).encode()).hexdigest()
                partial = self.local(RESERVED + '/parciais/' + key + '.part')
                positions[fid] = min(size, partial.stat().st_size) if partial.is_file() else 0
        with self.lock:
            self.byte_plan, self.byte_positions = planned, positions
            self.network_bytes = 0
            self.rate_samples = deque([(time.monotonic(), 0)])
            total, copied = sum(planned.values()), sum(positions.values())
            self.status.update(total_bytes=total, copied_bytes=copied,
                               unknown_size_files=unknown, progress_ready=True)
            stale = set(self.failures) - set(files)
            for fid in stale:
                del self.failures[fid]
            if stale:
                save_json(self.state / 'errors.json', self.failures)

    def update_bytes(self, fid, value):
        # Caller holds self.lock. O(1), even for large libraries.
        if fid not in self.byte_plan:
            return
        value = min(self.byte_plan[fid], max(0, value))
        previous = self.byte_positions.get(fid, 0)
        self.byte_positions[fid] = value
        self.status['copied_bytes'] += value - previous

    def record_failure(self, item, exc):
        with self.lock:
            fid = item['id']
            old = self.failures.get(fid, {})
            self.failures[fid] = {'id': fid, 'name': item['relative'], 'message': str(exc),
                'attempts': old.get('attempts', 0) + 1, 'time': time.strftime('%d/%m/%Y %H:%M:%S')}
            save_json(self.state / 'errors.json', self.failures)
            key = hashlib.sha256((fid + fingerprint(item)).encode()).hexdigest()
            partial = self.local(RESERVED + '/parciais/' + key + '.part')
            self.update_bytes(fid, partial.stat().st_size if partial.is_file() else 0)

    def clear_failure(self, fid):
        with self.lock:
            if fid in self.failures:
                del self.failures[fid]
                save_json(self.state / 'errors.json', self.failures)

    def retry_errors(self):
        with self.lock:
            if self.status['phase'] in ('verificando', 'baixando') or self.active:
                raise ValueError('Espere o ciclo terminar ou pause antes de tentar novamente.')
            if not self.failures:
                raise ValueError('Não há arquivos com erro para tentar novamente.')
            self.pause(False)
            self.event('Nova tentativa solicitada. Arquivos já concluídos serão reconhecidos.')

    def transfer_status(self):
        # Caller holds self.lock. Copy values so snapshots cannot observe mutations.
        active = list(self.active.values())
        self.status.update(bytes=sum(a['bytes'] for a in active),
                           size=sum(a['size'] for a in active),
                           speed=sum(a['speed'] for a in active),
                           active=[dict(a) for a in active],
                           current=' | '.join(a['name'] for a in active[:4]))

    def transfer(self, fid, item):
        self.check()
        path = self.local(item['relative'])
        with self.lock:
            previous = dict(self.manifest['files'].get(fid, {}))
        signature = fingerprint(item)
        if previous.get('fingerprint') == signature and previous.get('path') == item['relative'] and self.same_local(path, previous):
            self.clear_failure(fid)
            return
        self.guard()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256((fid + signature).encode()).hexdigest()
        part = self.local(RESERVED + '/parciais/' + key + '.part')
        initial = part.stat().st_size if part.exists() else 0
        expected = int(item.get('size', 0))
        needed = max(0, expected - initial)
        with self.lock:
            if shutil.disk_usage(self.destination).free < self.reserved_bytes + needed + 64 * 1024 * 1024:
                raise InsufficientSpace('Espaço livre insuficiente no RAID. Confira também a lixeira local.')
            self.reserved_bytes += needed
            self.active[fid] = {'name': item['relative'], 'bytes': initial, 'size': expected, 'speed': 0}
            self.transfer_status()
        started = time.monotonic()
        received = [initial]
        last_guard = [0.0]
        def check():
            self.check()
            if time.monotonic() - last_guard[0] > 5:
                self.guard(); last_guard[0] = time.monotonic()
        def progress(done, total):
            with self.lock:
                # Release the reservation as bytes are written to disk.
                nonlocal needed
                remaining = max(0, expected - done)
                if remaining < needed:
                    self.reserved_bytes -= needed - remaining
                    needed = remaining
                self.network_bytes += max(0, done - received[0])
                received[0] = done
                now = time.monotonic()
                if not self.rate_samples or now - self.rate_samples[-1][0] >= .5:
                    self.rate_samples.append((now, self.network_bytes))
                while len(self.rate_samples) > 1 and self.rate_samples[1][0] < now - 30:
                    self.rate_samples.popleft()
                self.update_bytes(fid, done)
                self.active[fid].update(bytes=done, size=total,
                    speed=max(0, done - initial) / max(.01, time.monotonic() - started))
                self.transfer_status()
        try:
            if item['mimeType'].startswith('application/vnd.google-apps.') and item['mimeType'] not in EXPORTS:
                url = 'https://drive.google.com/open?id=' + urllib.parse.quote(fid, safe='')
                data = ('[InternetShortcut]\nURL=' + url + '\n').encode()
                part.write_bytes(data); checksum = hashlib.md5(data).hexdigest()
                self.event(f'Salvo como link (formato nativo sem exportação): {item["relative"]}')
            else:
                checksum = self.drive.download(item, part, progress, check)
            self.check(); self.guard()
            # File replacement and manifest writes are serialized across workers.
            with self.lock:
                if path.exists():
                    self.archive(path, 'substituido')
                os.replace(part, path)
                stat = path.stat()
                self.manifest['files'][fid] = {'path': item['relative'], 'fingerprint': signature,
                    'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'md5': checksum}
                self.persist()
                self.update_bytes(fid, self.byte_plan.get(fid, 0))
                self.clear_failure(fid)
        finally:
            with self.lock:
                self.reserved_bytes -= needed
                self.active.pop(fid, None)
                self.transfer_status()

    def download_all(self, files):
        errors = []
        remaining = iter(files.items())
        pending = {}
        # Fixed capacity, dynamically bounded submissions: supports both increasing and decreasing live.
        pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='drive-download')
        def submit():
            self.check()
            try:
                fid, item = next(remaining)
            except StopIteration:
                return False
            pending[pool.submit(self.transfer, fid, item)] = item
            return True
        try:
            while True:
                self.check()
                while True:
                    with self.lock:
                        limit = self.validate_workers(self.config.get('workers', 4))
                        if len(pending) >= limit or not submit():
                            break
                if not pending:
                    break
                finished, _ = wait(pending, timeout=.2, return_when=FIRST_COMPLETED)
                for future in finished:
                    item = pending.pop(future)
                    try:
                        future.result()
                    except (Paused, AuthenticationRequired, StorageUnavailable, InsufficientSpace):
                        raise
                    except Exception as exc:
                        message = f'{item["relative"]}: {exc}'
                        errors.append(message); self.event(message)
                        self.record_failure(item, exc)
                    with self.lock:
                        self.status['done'] += 1
        finally:
            for future in pending:
                future.cancel()
            # Wait for in-flight workers to pause/finish before scan deletion or next cycle.
            pool.shutdown(wait=True, cancel_futures=True)
        if errors:
            raise RuntimeError(f'{len(errors)} arquivo(s) com erro. Exclusões adiadas. Primeiro erro: {errors[0]}')

    def sync(self):
        with self.operation_lock:
            return self._sync()

    def _sync(self):
        self.guard(); self.check()
        if self.destination.is_symlink():
            raise RuntimeError('Destino é link simbólico.')
        self.destination.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.status.update(phase='verificando', error='', current='', done=0, total=0, bytes=0, size=0, speed=0, progress_ready=False)
        relocations.recover(self)
        files, folders = self.scan()
        self.guard(); self.check()
        self.local(RESERVED + '/parciais').mkdir(parents=True, exist_ok=True)
        relocations.apply(self, files)
        old = self.manifest['files']
        # Move old paths out of the way before applying renamed files, including swaps.
        for fid, entry in list(old.items()):
            if fid in files and entry['path'] != files[fid]['relative']:
                self.check(); self.archive(self.local(entry['path']), 'renomeado')
                del old[fid]; self.persist()
        for folder in sorted(folders, key=lambda s: len(Path(s).parts)):
            self.check(); self.guard()
            path = self.local(folder)
            if path.exists() and not path.is_dir():
                self.archive(path, 'conflito')
            path.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.status.update(phase='baixando', total=len(files))
        self.prepare_progress(files)
        self.download_all(files)
        # Deletion only after a complete scan AND all planned transfers succeeded.
        planned_paths = {item['relative'] for item in files.values()} | set(folders)
        for fid, entry in list(old.items()):
            if fid not in files:
                self.check()
                # A new file/folder may already own this path; its predecessor was archived on conflict.
                if entry['path'] not in planned_paths:
                    self.archive(self.local(entry['path']), 'removido-no-drive')
                del old[fid]; self.persist()
        for folder in sorted(set(self.manifest['folders']) - set(folders), key=lambda s: len(Path(s).parts), reverse=True):
            self.guard()
            path = self.local(folder)
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        self.manifest['folders'] = folders
        self.manifest['last_sync'] = time.strftime('%d/%m/%Y %H:%M:%S')
        self.persist()
        with self.lock:
            self.status.update(phase='aguardando', current='', done=len(files), bytes=0, size=0,
                               speed=0, last_sync=self.manifest['last_sync'])
        try:
            self.maintenance.write_checkpoint()
        except Exception as exc:
            self.maintenance.checkpoint_error = str(exc)
            self.event('Não foi possível atualizar o checkpoint de recuperação: ' + str(exc))
        self.event(f'Ciclo concluído: {len(files)} arquivos, {len(folders)} pastas.')

    def loop(self):
        while True:
            self.wake.clear()
            if self.config['paused']:
                with self.lock:
                    self.status['phase'] = 'pausado'
                self.wake.wait(60)
                continue
            try:
                self.sync()
            except Paused:
                with self.lock:
                    self.status.update(phase='pausado', speed=0)
            except AuthenticationRequired as e:
                self.auth_error = str(e)
                self.alert_cache = (0, [])
                save_json(self.state/'auth-status.json', {'error':self.auth_error})
                self.pause(True)
                with self.lock: self.status.update(phase='erro', error=self.auth_error, speed=0)
                self.event(self.auth_error)
            except Exception as e:
                with self.lock:
                    self.status.update(phase='erro', error=str(e), speed=0)
                self.event(str(e))
            self.wake.wait(self.config['interval'])

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def clear_auth_error(self):
        self.auth_error = ''
        save_json(self.state/'auth-status.json', {})
        self.alert_cache = (0, [])

    def collect_alerts(self):
        now = time.monotonic()
        if now-self.alert_cache[0] < 15 and self.alert_cache[0]: return self.alert_cache[1]
        alerts = []
        if self.auth_error:
            alerts.append({'kind':'auth','severity':'error','message':self.auth_error})
        try:
            self.guard()
            usage = shutil.disk_usage(self.destination if self.destination.exists() else self.mountpoint)
            if usage.free < max(256*1024*1024, usage.total*.02):
                alerts.append({'kind':'space','severity':'warning','message':f'Pouco espaço livre no volume: {usage.free//(1024*1024)} MiB.'})
            info = self.mountpoint.stat()
            base = Path('/sys/dev/block') / f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}' / 'md'
            degraded = base/'degraded'
            if degraded.exists() and int(degraded.read_text().strip()) > 0:
                alerts.append({'kind':'raid','severity':'error','message':'RAID degradado: há membros ausentes. Confira o armazenamento.'})
        except Exception as exc:
            alerts.append({'kind':'storage','severity':'error','message':str(exc)})
        if self.maintenance.checkpoint_error:
            alerts.append({'kind':'recovery','severity':'warning','message':'O checkpoint de recuperação não foi atualizado: '+self.maintenance.checkpoint_error})
        report = self.maintenance.snapshot().get('report', {})
        if report.get('failed',0):
            alerts.append({'kind':'integrity','severity':'warning','message':f'A última verificação encontrou {report["failed"]} arquivo(s) com problema. Veja o relatório de manutenção.'})
        self.alert_cache = (now, alerts)
        return alerts

    def snapshot(self):
        maintenance = self.maintenance.snapshot()
        alerts = self.collect_alerts()
        with self.lock:
            now = time.monotonic()
            samples = self.rate_samples
            recent = next((sample for sample in samples if sample[0] >= now - 30), samples[-1] if samples else (now, 0))
            elapsed = now - recent[0]
            speed = (self.network_bytes - recent[1]) / elapsed if elapsed >= 1 and self.status['phase'] == 'baixando' and not self.config['paused'] else 0
            remaining = max(0, self.status.get('total_bytes', 0) - self.status.get('copied_bytes', 0))
            eta = remaining / speed if speed > 0 and remaining > 0 else None
            failures = sorted(self.failures.values(), key=lambda f: (f['time'], f['id']), reverse=True)
            return dict(self.status, maintenance=maintenance, alerts=alerts, maintenance_supported=True, remaining_bytes=remaining, overall_speed=speed, eta_seconds=eta,
                        errors=[dict(f) for f in failures[:100]], error_count=len(failures),
                        connected=(self.state / 'tokens.json').exists() and not bool(self.auth_error),
                        credentials=(self.state / 'client.json').exists(), paused=self.config['paused'],
                        root=self.config['root'], interval=self.config['interval'], workers=self.config['workers'], workers_live=True, workers_draining=max(0,len(self.active)-self.config['workers']), bandwidth_mib=self.config['bandwidth_mib'],
                        destination=str(self.destination), tracked=len(self.manifest['files']))
