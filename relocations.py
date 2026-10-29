"""Journaled same-volume moves keyed by Drive ID. No redownload for metadata-only moves."""
import hashlib
import os
from pathlib import Path
from drive import load_json, save_json

JOURNAL = 'moves.pending.json'

def durable_move(source, target):
    os.replace(source, target)
    for directory in {source.parent, target.parent}:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

def same_content(item, entry):
    checksum = item.get('md5Checksum')
    if checksum and entry.get('md5'):
        return checksum == entry['md5'] and int(item.get('size', -1)) == entry.get('size')
    from engine import fingerprint
    return fingerprint(item) == entry.get('fingerprint')

def verify_file(engine, path, entry):
    if not path.is_file() or path.stat().st_size != entry.get('size'):
        return False
    digest = hashlib.md5()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            engine.check(); digest.update(chunk)
    return digest.hexdigest() == entry.get('md5')

def execute(engine, journal):
    location = engine.state / JOURNAL
    operations = journal['operations']
    if journal['phase'] == 'stage':
        for operation in operations:
            engine.check(); engine.guard()
            source = engine.local(operation['source'])
            stage = engine.local(operation['stage'])
            if not stage.exists():
                if not engine.same_local(source, operation['entry']):
                    raise RuntimeError('Arquivo mudou durante a movimentação. A operação foi preservada para recuperação.')
                stage.parent.mkdir(parents=True, exist_ok=True)
                durable_move(source, stage)
        journal['phase'] = 'commit'
        save_json(location, journal)
    for operation in operations:
        engine.check(); engine.guard()
        stage = engine.local(operation['stage'])
        target = engine.local(operation['target'])
        if stage.exists():
            # All sources were staged first, so swaps and folder renames cannot overwrite a source.
            parents = []
            parent = target.parent
            while parent != engine.destination:
                parents.append(parent); parent = parent.parent
            for parent in reversed(parents):
                if parent.exists() and not parent.is_dir():
                    engine.archive(parent, 'conflito-movimento')
                parent.mkdir(exist_ok=True)
            if target.exists():
                engine.archive(target, 'conflito-movimento')
            durable_move(stage, target)
        elif not verify_file(engine, target, operation['entry']):
            raise RuntimeError('Movimentação incompleta: mantenha os dados e o diário para recuperação; destino não confere.')
        stat = target.stat()
        entry = dict(operation['entry'], path=operation['target'],
                     fingerprint=operation['fingerprint'], size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        with engine.lock:
            engine.manifest['files'][operation['id']] = entry
            engine.persist()
        engine.event('Movido localmente, sem download: ' + operation['target'])
    location.unlink(missing_ok=True)
    for operation in operations:
        parent = engine.local(operation['stage']).parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()

def recover(engine):
    journal = load_json(engine.state / JOURNAL)
    if journal:
        engine.event('Recuperando movimentações locais interrompidas.')
        execute(engine, journal)

def apply(engine, files):
    from engine import fingerprint, RESERVED
    recover(engine)
    operations = []
    for fid, item in files.items():
        entry = engine.manifest['files'].get(fid)
        if not entry or not same_content(item, entry):
            continue
        source = engine.local(entry['path'])
        if not engine.same_local(source, entry):
            continue
        if entry['path'] == item['relative']:
            # A metadata edit can increment the remote version while bytes stay unchanged.
            if entry['fingerprint'] != fingerprint(item):
                entry['fingerprint'] = fingerprint(item)
                engine.persist()
            continue
        name = hashlib.sha256(fid.encode()).hexdigest() + '.data'
        operations.append({'id': fid, 'source': entry['path'], 'target': item['relative'],
            'stage': RESERVED + '/moves/' + name, 'entry': dict(entry), 'fingerprint': fingerprint(item)})
    if operations:
        journal = {'schema': 1, 'phase': 'stage', 'operations': operations}
        save_json(engine.state / JOURNAL, journal)
        execute(engine, journal)
