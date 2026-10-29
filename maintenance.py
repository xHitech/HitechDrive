"""Explicit, exclusive maintenance: recovery, verified adoption, audits and reviewed cleanup."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading
import time

from bandwidth import BandwidthLimiter
from drive import load_json, save_json

class MaintenanceCancelled(Exception):
    pass

class Maintenance:
    def __init__(self, engine):
        self.engine = engine
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.task = {'kind': None, 'state': 'idle', 'done': 0, 'total': 0, 'bytes': 0,
                     'current': '', 'error': '', 'ok': 0, 'failed': 0, 'skipped': 0}
        self.report = load_json(engine.state/'audit-report.json')
        self.previews = {}
        self.last_guard = 0
        self.checkpoint_error = ''

    def snapshot(self):
        with self.lock:
            try: available = self.engine.local('.drive-espelho/recovery.json').is_file()
            except Exception: available = False
            return dict(self.task, report=copy.deepcopy(self.report), checkpoint_available=available)

    def idle(self):
        e = self.engine
        if not e.config['paused'] or e.active or e.status['phase'] in ('baixando', 'verificando'):
            raise ValueError('Pause e espere as transferências pararem antes da manutenção.')
        if (e.state/'moves.pending.json').exists():
            raise ValueError('Há uma movimentação interrompida. Retome a sincronização para recuperá-la primeiro.')
        e.guard()

    def check(self):
        if self.cancelled.is_set():
            raise MaintenanceCancelled()
        if time.monotonic()-self.last_guard >= 5:
            self.engine.guard(); self.last_guard=time.monotonic()

    def digest(self, path, limiter):
        e = self.engine
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('O caminho não é um arquivo regular.')
        result = hashlib.md5()
        with path.open('rb') as stream:
            while True:
                self.check()
                chunk = stream.read(256*1024)
                if not chunk: break
                limiter.acquire(len(chunk), self.check)
                result.update(chunk)
                with self.lock: self.task['bytes'] += len(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('O arquivo mudou durante a verificação.')
        return result.hexdigest(), after

    def start(self, kind, rate=8):
        if kind not in ('audit', 'rebuild'):
            raise ValueError('Operação de manutenção inválida.')
        limiter = BandwidthLimiter(rate)
        with self.lock:
            if self.task['state'] == 'running':
                raise ValueError('Já existe uma manutenção em andamento.')
            self.idle()
            if not self.engine.operation_lock.acquire(blocking=False):
                raise ValueError('Aguarde a operação atual terminar.')
            self.cancelled.clear()
            self.task = {'kind': kind, 'state': 'running', 'done': 0, 'total': 0, 'bytes': 0,
                         'current': '', 'error': '', 'ok': 0, 'failed': 0, 'skipped': 0}
        thread = threading.Thread(target=self.run, args=(kind, limiter), daemon=True, name='hitech-maintenance')
        try:
            thread.start()
        except Exception as exc:
            with self.lock: self.task.update(state='error', error=str(exc))
            self.engine.operation_lock.release()
            raise

    def run(self, kind, limiter):
        findings = []
        e = self.engine
        try:
            if kind == 'audit':
                entries = copy.deepcopy(e.manifest['files'])
                jobs = [(fid, entry, None) for fid, entry in entries.items()]
            else:
                files, folders = e.scan(check=self.check)
                jobs = [(fid, {'path': item['relative'], 'md5': item.get('md5Checksum'),
                    'size': int(item['size']) if 'size' in item else None}, item) for fid, item in files.items()]
            with self.lock: self.task['total'] = len(jobs)
            for fid, entry, remote in jobs:
                self.check()
                with self.lock: self.task['current'] = entry['path']
                outcome = 'ok'; message = ''
                try:
                    if not entry.get('md5'):
                        outcome = 'skipped'; message = 'Sem checksum de referência; não será adotado sem evidência.'
                    else:
                        path = e.local(entry['path'])
                        digest, local_stat = self.digest(path, limiter)
                        if digest != entry['md5'] or local_stat.st_size != entry['size']:
                            outcome = 'failed'; message = 'Conteúdo ou tamanho diverge da referência.'
                        elif kind == 'rebuild':
                            from engine import fingerprint
                            with e.lock:
                                e.manifest['files'][fid] = {'path': entry['path'], 'md5': digest,
                                    'size': local_stat.st_size, 'mtime_ns': local_stat.st_mtime_ns,
                                    'fingerprint': fingerprint(remote)}
                                e.persist()
                except MaintenanceCancelled: raise
                except Exception as exc:
                    outcome = 'failed'; message = str(exc)
                with self.lock:
                    self.task['done'] += 1
                    self.task['ok' if outcome == 'ok' else outcome] += 1
                if outcome != 'ok':
                    findings.append({'path': entry['path'], 'status': outcome, 'message': message})
            with self.lock: self.task['state'] = 'complete'
        except MaintenanceCancelled:
            with self.lock: self.task['state'] = 'cancelled'
        except Exception as exc:
            with self.lock: self.task.update(state='error', error=str(exc))
        finally:
            try:
                with self.lock:
                    self.report = {key: value for key, value in self.task.items() if key not in ('report',)}
                    self.report.update(finished=time.strftime('%d/%m/%Y %H:%M:%S'), findings=findings[:100])
                    save_json(e.state/'audit-report.json', self.report)
            except Exception as exc:
                with self.lock:
                    self.task.update(state='error', error='Não foi possível salvar o relatório: ' + str(exc))
                    self.report.update(state='error', error=self.task['error'])
            finally:
                e.operation_lock.release()
            e.alert_cache = (0, [])
            e.event('Manutenção ' + kind + ': ' + self.task['state'])

    def export(self):
        self.idle()
        e = self.engine
        if not e.operation_lock.acquire(blocking=False):
            raise ValueError('Aguarde a manutenção terminar.')
        try:
            return self.bundle()
        finally: e.operation_lock.release()

    def bundle(self):
        e = self.engine
        with e.lock:
            account = load_json(e.state/'account.json')
            return {'format':'hitechdrive-recovery', 'schema':1,
                'created':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'instance':load_json(e.state/'instance.json'),
                'owner':{'permissionId':account.get('permissionId')},
                'config':dict(e.config,paused=True), 'manifest':copy.deepcopy(e.manifest)}

    def write_checkpoint(self):
        e = self.engine
        if not load_json(e.state/'account.json').get('permissionId'): return
        e.guard()
        checkpoint = e.local('.drive-espelho/recovery.json')
        checkpoint.parent.mkdir(parents=True,exist_ok=True)
        save_json(checkpoint,self.bundle())
        self.checkpoint_error = ''

    def restore_checkpoint(self):
        self.idle()
        backup=load_json(self.engine.local('.drive-espelho/recovery.json'))
        if not backup: raise ValueError('Não existe um checkpoint de recuperação neste volume.')
        self.restore(backup)

    def restore(self, backup):
        self.idle(); e = self.engine
        if not e.operation_lock.acquire(blocking=False):
            raise ValueError('Aguarde a manutenção terminar.')
        try:
            if e.manifest['files']:
                raise ValueError('A recuperação por importação exige um manifesto vazio; a réplica atual não será sobrescrita.')
            if backup.get('format') != 'hitechdrive-recovery' or backup.get('schema') != 1:
                raise ValueError('Arquivo de recuperação incompatível.')
            instance = backup['instance']; config = backup['config']; manifest = backup['manifest']
            if not e.expected_uuid or instance.get('volume_uuid') != e.expected_uuid:
                raise ValueError('O backup pertence a outro volume. Configure o volume correto antes de importar.')
            owner = backup.get('owner', {}).get('permissionId')
            existing = load_json(e.state/'account.json').get('permissionId')
            if existing and owner != existing:
                raise ValueError('A conta do backup difere da conta conectada.')
            if not owner: raise ValueError('O backup não identifica a conta da réplica.')
            root = config.get('root', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', root): raise ValueError('Origem inválida no backup.')
            files = manifest.get('files')
            if not isinstance(files, dict) or len(files) > 200000: raise ValueError('Manifesto inválido ou grande demais.')
            for fid, entry in files.items():
                if not isinstance(fid, str) or not isinstance(entry, dict): raise ValueError('Registro inválido no manifesto.')
                if Path(entry['path']).parts[0].startswith('.drive-espelho'):
                    raise ValueError('O manifesto não pode referenciar dados internos da réplica.')
                e.local(entry['path'])
                if not re.fullmatch(r'[a-fA-F0-9]{32}', entry.get('md5', '')): raise ValueError('Checksum inválido no backup.')
                if not isinstance(entry.get('size'), int) or entry['size'] < 0: raise ValueError('Tamanho inválido no backup.')
                if not isinstance(entry.get('mtime_ns'), int) or not isinstance(entry.get('fingerprint'), str):
                    raise ValueError('Metadados inválidos no backup.')
            for folder in manifest.get('folders', []):
                if Path(folder).parts[0].startswith('.drive-espelho'): raise ValueError('Pasta interna no manifesto.')
                e.local(folder)
            restored = {'root': root, 'interval': max(60, min(int(config.get('interval',300)),86400)),
                'workers': e.validate_workers(config.get('workers',4)), 'paused': True,
                'bandwidth_mib': e.bandwidth.validate(config.get('bandwidth_mib',0)),
                'internet_mbps': 0}
            documents = {'account.json': {'permissionId': owner}, 'config.json': restored, 'manifest.json': manifest}
            # Journal allows the next startup to finish an interrupted multi-file import.
            save_json(e.state/'recovery.pending.json', documents)
            for name, content in documents.items(): save_json(e.state/name, content)
            (e.state/'recovery.pending.json').unlink()
            with e.lock:
                e.config = restored; e.manifest = copy.deepcopy(manifest)
                e.status.update(phase='pausado', error='', progress_ready=False, done=0, total=0)
                e.bandwidth.set_limit(restored['bandwidth_mib'])
            e.event('Manifesto recuperado sem baixar novamente. Reconecte a conta se necessário.')
        finally: e.operation_lock.release()

    def cleanup_preview(self):
        self.idle(); e = self.engine
        if not e.operation_lock.acquire(blocking=False): raise ValueError('Aguarde a manutenção terminar.')
        try:
            entries = []
            for kind, relative in [('trash', '.drive-espelho/lixeira'), ('partials', '.drive-espelho/parciais')]:
                root = e.local(relative)
                if not root.exists(): continue
                for parent, dirs, names in os.walk(root, followlinks=False):
                    dirs[:] = [d for d in dirs if not (Path(parent)/d).is_symlink()]
                    for name in names:
                        path = Path(parent)/name
                        if path.is_symlink() or not path.is_file(): continue
                        info = path.stat()
                        entries.append({'path':str(path.relative_to(e.destination)), 'kind':kind,
                            'size':info.st_size,'mtime_ns':info.st_mtime_ns,'inode':info.st_ino})
            token = secrets.token_urlsafe(32)
            with self.lock:
                self.previews = {token: {'created':time.monotonic(),'entries':entries}}
            return {'token':token, 'count':len(entries),'bytes':sum(x['size'] for x in entries),
                'trash_bytes':sum(x['size'] for x in entries if x['kind']=='trash'),
                'partial_bytes':sum(x['size'] for x in entries if x['kind']=='partials'),
                'entries':[{'path':x['path'],'size':x['size'],'kind':x['kind']} for x in entries[:100]]}
        finally: e.operation_lock.release()

    def cleanup(self, token, kind, confirmation):
        if confirmation != 'APAGAR DEFINITIVAMENTE' or kind not in ('trash','partials','all'):
            raise ValueError('Selecione o conteúdo e confirme a exclusão definitiva.')
        self.idle(); e=self.engine
        if not e.operation_lock.acquire(blocking=False): raise ValueError('Aguarde a manutenção terminar.')
        try:
            with self.lock: preview=self.previews.pop(token,None)
            if not preview or time.monotonic()-preview['created']>600:
                raise ValueError('Prévia expirada. Calcule o espaço novamente antes de excluir.')
            self.cancelled.clear()
            removed=skipped=0
            for entry in preview['entries']:
                if kind!='all' and entry['kind']!=kind:continue
                self.check(); e.guard()
                # Only exact regular files reviewed in the preview can be removed. Never follow links.
                path=e.local(entry['path'])
                try: info=path.lstat()
                except FileNotFoundError:continue
                if not stat.S_ISREG(info.st_mode) or (info.st_size,info.st_mtime_ns,info.st_ino)!=(entry['size'],entry['mtime_ns'],entry['inode']):
                    skipped+=1;continue
                path.unlink();removed+=1
            e.alert_cache = (0, [])
            e.event(f'Limpeza confirmada: {removed} arquivos removidos; {skipped} alterados preservados.')
            return {'removed':removed,'skipped':skipped}
        finally:e.operation_lock.release()
