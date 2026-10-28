import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drive import Drive, FOLDER, Paused, load_json
from engine import Engine, component

class FakeDrive:
    def __init__(self):
        self.items = []
        self.fail_scan = False
        self.fail_download = False
        self.downloads = 0
    def json(self, *args):
        return {'id': 'root', 'mimeType': FOLDER}
    def children(self, folder):
        if self.fail_scan:
            raise RuntimeError('Simulated network failure')
        return self.items if folder == 'root' else []
    def catalog(self, check, progress):
        result = {}
        stack = ['root']
        while stack:
            parent = stack.pop()
            for meta in self.children(parent):
                result[meta['id']] = dict(meta, parents=[parent])
                if meta['mimeType'] == FOLDER: stack.append(meta['id'])
        return result
    def download(self, item, part, progress, check):
        check()
        if self.fail_download:
            raise RuntimeError('Simulated interrupted transfer')
        self.downloads += 1
        data = item.get('content', b'example')
        part.write_bytes(data); progress(len(data), len(data))
        return hashlib.md5(data).hexdigest()

def item(fid='a', name='filme.mkv', version='1', content=b'example'):
    return {'id': fid, 'name': name, 'version': version, 'mimeType': 'video/x-matroska', 'size': len(content), 'content': content}

class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.e = Engine(base/'state', base/'media', guard=lambda:None)
        self.e.drive = self.d = FakeDrive()
        self.e.config['paused'] = False
    def test_download_unchanged_and_recoverable_deletion(self):
        self.d.items = [item()]; self.e.sync()
        self.assertEqual((self.e.destination/'filme.mkv').read_bytes(), b'example')
        self.e.sync(); self.assertEqual(self.d.downloads, 1)
        self.d.items = []; self.e.sync()
        self.assertFalse((self.e.destination/'filme.mkv').exists())
        self.assertEqual(next((self.e.destination/'.drive-espelho/lixeira').rglob('filme.mkv')).read_bytes(), b'example')
        self.assertEqual(load_json(self.e.state/'manifest.json')['files'], {})
    def test_failed_scan_never_deletes(self):
        self.d.items=[item()]; self.e.sync(); self.d.fail_scan=True
        with self.assertRaises(RuntimeError): self.e.sync()
        self.assertTrue((self.e.destination/'filme.mkv').exists())
    def test_failed_transfer_blocks_remote_deletions(self):
        self.d.items=[item()]; self.e.sync()
        self.d.items=[item('b','new.mkv')]; self.d.fail_download=True
        with self.assertRaises(RuntimeError): self.e.sync()
        self.assertTrue((self.e.destination/'filme.mkv').exists())
    def test_duplicate_names_remain_distinct(self):
        self.d.items=[item('a','x',content=b'a'),item('b','x',content=b'b')]; self.e.sync()
        self.assertEqual((self.e.destination/'x').read_bytes(), b'a')
        self.assertEqual((self.e.destination/'x~b').read_bytes(), b'b')
    def test_renaming_and_local_edits_preserved(self):
        self.d.items=[item()]; self.e.sync()
        path=self.e.destination/'filme.mkv'; path.write_bytes(b'local edits')
        self.d.items=[item(name='renamed.mkv')]; self.e.sync()
        self.assertEqual((self.e.destination/'renamed.mkv').read_bytes(), b'example')
        self.assertEqual(next((self.e.destination/'.drive-espelho/lixeira').rglob('filme.mkv')).read_bytes(), b'local edits')
    def test_symlink_escape_blocked(self):
        self.e.destination.mkdir(); outside=Path(self.temp.name)/'outside'; outside.mkdir()
        (self.e.destination/'filme.mkv').symlink_to(outside/'anything')
        self.d.items=[item()]
        with self.assertRaises(RuntimeError): self.e.sync()
        self.assertEqual(list(outside.iterdir()), [])
    def test_unmounted_raid_cannot_create_destination(self):
        self.e.guard=lambda: (_ for _ in ()).throw(RuntimeError('unmounted'))
        with self.assertRaises(RuntimeError): self.e.sync()
        self.assertFalse(self.e.destination.exists())
    def test_pause_does_not_delete(self):
        self.d.items=[item()]; self.e.sync(); self.e.config['paused']=True
        self.d.items=[]
        with self.assertRaises(Paused): self.e.sync()
        self.assertTrue((self.e.destination/'filme.mkv').exists())
    def test_unsafe_names(self):
        for raw in ('..','.', '../evil', '/etc/passwd', '.drive-espelho','x\x00y'):
            name=component(raw)
            self.assertNotIn('/',name);self.assertNotIn('\x00',name)
            self.assertNotIn(name, ('.','..'));self.assertFalse(name.startswith('.drive-espelho'))
    def test_unsupported_native_is_explicit_link(self):
        self.d.items=[dict(item(), mimeType='application/vnd.google-apps.form')];self.e.sync()
        self.assertIn(b'https://drive.google.com/open?id=a',(self.e.destination/'filme.mkv.url').read_bytes())
    def test_restart_uses_persisted_manifest(self):
        self.d.items=[item()];self.e.sync()
        new=Engine(self.e.state,self.e.destination,guard=lambda:None);new.drive=self.d
        new.config['paused']=False;new.sync();self.assertEqual(self.d.downloads,1)

class Response(io.BytesIO):
    def __init__(self,data,status,headers):
        super().__init__(data);self.status=status;self.headers=headers

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'part'; self.drive=Drive(self.tmp.name)
        self.meta={'id':'x','mimeType':'video/mp4','version':'1','size':'6','md5Checksum':hashlib.md5(b'abcdef').hexdigest()}
        self.drive.json=lambda *a:{'version':'1'}
    def download(self):
        return self.drive.download(self.meta,self.path,lambda *a:None,lambda:None)
    def test_resume_validates_range(self):
        self.path.write_bytes(b'abc')
        with patch.object(self.drive,'request',return_value=Response(b'def',206,{'Content-Range':'bytes 3-5/6'})) as request:
            self.download()
            self.assertEqual(request.call_args.args[2],{'Range':'bytes=3-'})
        self.assertEqual(self.path.read_bytes(),b'abcdef')
    def test_ignored_range_restarts_instead_of_appending(self):
        self.path.write_bytes(b'abc')
        with patch.object(self.drive,'request',return_value=Response(b'abcdef',200,{})):
            self.download()
        self.assertEqual(self.path.read_bytes(),b'abcdef')
    def test_checksum_failure_discards_corrupt_partial(self):
        with patch.object(self.drive,'request',return_value=Response(b'badbad',200,{})):
            with self.assertRaises(RuntimeError):self.download()
        self.assertFalse(self.path.exists())
    def test_bad_range_never_appends(self):
        self.path.write_bytes(b'abc')
        with patch.object(self.drive,'request',return_value=Response(b'xxx',206,{'Content-Range':'bytes 0-2/6'})):
            with self.assertRaises(RuntimeError):self.download()
        self.assertEqual(self.path.read_bytes(),b'abc')
    def test_remote_version_change_never_commits(self):
        self.drive.json=lambda *a:{'version':'2'}
        with patch.object(self.drive,'request',return_value=Response(b'abcdef',200,{})):
            with self.assertRaises(RuntimeError):self.download()
        self.assertFalse(self.path.exists())
    def test_oauth_state_mismatch_rejected(self):
        self.drive.pending=('expected','verifier','http://127.0.0.1:8765/oauth/callback',__import__('time').time())
        with self.assertRaises(ValueError):self.drive.exchange('fake','wrong')

class ReplacementTests(unittest.TestCase):
    setUp = MirrorTests.setUp
    def test_one_bad_file_does_not_block_other_downloads(self):
        self.d.items=[item('a','bad.mkv'),item('b','good.mkv')]
        original=self.d.download
        def download(item, *args):
            if item['id']=='a': raise RuntimeError('quota')
            return original(item,*args)
        self.d.download=download
        with self.assertRaises(RuntimeError):self.e.sync()
        self.assertTrue((self.e.destination/'good.mkv').exists())
        self.assertFalse((self.e.destination/'bad.mkv').exists())
    def test_deleted_id_path_reused_by_new_id_does_not_trash_new_file(self):
        self.d.items=[item('a','same.mkv',content=b'old')];self.e.sync()
        self.d.items=[item('b','same.mkv',content=b'new')];self.e.sync()
        self.assertEqual((self.e.destination/'same.mkv').read_bytes(),b'new')
        self.assertNotIn('a',self.e.manifest['files'])
    def test_file_replaced_by_folder_keeps_new_contents(self):
        self.d.items=[item('a','movie')];self.e.sync()
        self.d.items=[{'id':'folder','name':'movie','mimeType':FOLDER}]
        original=self.d.children
        self.d.children=lambda fid:[item('new','new.mkv')] if fid=='folder' else original(fid)
        self.e.sync()
        self.assertEqual((self.e.destination/'movie/new.mkv').read_bytes(),b'example')

if __name__=='__main__':unittest.main()

class ParallelTests(unittest.TestCase):
    setUp = MirrorTests.setUp

    def test_bounded_parallelism_and_manifest_integrity(self):
        import threading
        import time
        self.e.config['workers'] = 3
        self.d.items = [item(str(i), f'{i}.mkv') for i in range(12)]
        original = self.d.download
        gate = threading.Barrier(3, timeout=5)
        lock = threading.Lock()
        state = {'running': 0, 'peak': 0, 'entered': 0}
        def download(meta, *args):
            with lock:
                state['running'] += 1
                state['entered'] += 1
                first_wave = state['entered'] <= 3
                state['peak'] = max(state['peak'], state['running'])
            try:
                if first_wave: gate.wait()
                time.sleep(.01)
                return original(meta, *args)
            finally:
                with lock: state['running'] -= 1
        self.d.download = download
        self.e.sync()
        self.assertEqual(state['peak'], 3)
        self.assertEqual(len(load_json(self.e.state/'manifest.json')['files']), 12)
        self.assertEqual(self.e.status['done'], 12)
        self.assertEqual(self.e.active, {})
        self.assertEqual(self.e.reserved_bytes, 0)

    def test_pause_drains_workers_and_preserves_old_files(self):
        import threading
        self.d.items = [item('old', 'old.mkv')]; self.e.sync()
        self.e.config['workers'] = 2
        self.d.items = [item(str(i), f'{i}.mkv') for i in range(10)]
        gate = threading.Barrier(2, timeout=5)
        def download(meta, part, progress, check):
            part.write_bytes(b'partial')
            gate.wait()
            self.e.pause(True)
            check()
        self.d.download = download
        with self.assertRaises(Paused): self.e.sync()
        self.assertTrue((self.e.destination/'old.mkv').exists())
        self.assertEqual(self.e.active, {})
        self.assertEqual(self.e.reserved_bytes, 0)
        self.assertEqual(len(list((self.e.destination/'.drive-espelho/parciais').glob('*.part'))), 2)

    def test_settings_worker_limit(self):
        self.e.config['paused'] = True
        self.e.settings('root', 300, 8)
        self.assertEqual(self.e.config['workers'], 8)
        for value in (0, 9):
            with self.assertRaises(ValueError): self.e.settings('root', 300, value)
