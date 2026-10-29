from pathlib import Path
import hashlib
import unittest
from unittest.mock import patch
import os
from engine import Engine
import test_mirror

def remote(fid,name,data,version='1'):
    return dict(test_mirror.item(fid,name,version,data),md5Checksum=hashlib.md5(data).hexdigest())

class RelocationTests(unittest.TestCase):
    setUp=test_mirror.MirrorTests.setUp
    def test_rename_with_new_version_uses_id_and_checksum_without_download(self):
        self.d.items=[remote('a','old.cbz',b'book')];self.e.sync()
        self.d.items=[remote('a','new.cbz',b'book','2')];self.e.sync()
        self.assertEqual(self.d.downloads,1)
        self.assertEqual((self.e.destination/'new.cbz').read_bytes(),b'book')
        self.assertFalse((self.e.destination/'old.cbz').exists())
        self.assertEqual(self.e.manifest['files']['a']['path'],'new.cbz')
    def test_metadata_only_version_update_does_not_redownload(self):
        self.d.items=[remote('a','book',b'book')];self.e.sync()
        self.d.items[0]['version']='2';self.e.sync()
        self.assertEqual(self.d.downloads,1)
    def test_swapped_names_do_not_overwrite_sources(self):
        self.d.items=[remote('a','A',b'aaa'),remote('b','B',b'bbb')];self.e.sync()
        self.d.items=[remote('a','B',b'aaa','2'),remote('b','A',b'bbb','2')];self.e.sync()
        self.assertEqual((self.e.destination/'A').read_bytes(),b'bbb')
        self.assertEqual((self.e.destination/'B').read_bytes(),b'aaa')
        self.assertEqual(self.d.downloads,2)
    def test_folder_rename_moves_children(self):
        folder={'id':'folder','name':'Old','mimeType':'application/vnd.google-apps.folder'}
        book=remote('a','book.cbz',b'book')
        self.d.children=lambda parent:[folder] if parent=='root' else [book] if parent=='folder' else []
        self.e.sync();folder['name']='New';self.e.sync()
        self.assertEqual(self.d.downloads,1)
        self.assertEqual((self.e.destination/'New/book.cbz').read_bytes(),b'book')
        self.assertFalse((self.e.destination/'Old').exists())
    def test_changed_local_content_is_preserved_and_remote_downloaded(self):
        self.d.items=[remote('a','A',b'original')];self.e.sync()
        (self.e.destination/'A').write_bytes(b'local change')
        self.d.items=[remote('a','B',b'original','2')];self.e.sync()
        self.assertEqual(self.d.downloads,2)
        self.assertEqual(next((self.e.destination/'.drive-espelho/lixeira').rglob('A')).read_bytes(),b'local change')
    def test_staging_interruption_resumes_from_journal(self):
        self.d.items=[remote('a','A',b'aaa'),remote('b','B',b'bbb')];self.e.sync()
        self.d.items=[remote('a','B',b'aaa','2'),remote('b','A',b'bbb','2')]
        original=os.replace;count=[0]
        def replace(source,target):
            if str(target).endswith('.data'):
                count[0]+=1
                if count[0]==2:raise OSError('simulated power loss')
            return original(source,target)
        with patch('relocations.os.replace',side_effect=replace):
            with self.assertRaises(OSError):self.e.sync()
        self.assertTrue((self.e.state/'moves.pending.json').exists())
        self.e.sync()
        self.assertFalse((self.e.state/'moves.pending.json').exists())
        self.assertEqual((self.e.destination/'A').read_bytes(),b'bbb')
        self.assertEqual((self.e.destination/'B').read_bytes(),b'aaa')
        self.assertEqual(self.d.downloads,2)
    def test_crash_after_move_before_manifest_is_recovered(self):
        self.d.items=[remote('a','A',b'aaa')];self.e.sync()
        self.d.items=[remote('a','B',b'aaa','2')]
        with patch.object(self.e,'persist',side_effect=OSError('crash')):
            with self.assertRaises(OSError):self.e.sync()
        restarted=Engine(self.e.state,self.e.destination,guard=lambda:None)
        restarted.config['paused']=False;restarted.drive=self.d
        restarted.sync()
        self.assertEqual((self.e.destination/'B').read_bytes(),b'aaa')
        self.assertFalse((self.e.state/'moves.pending.json').exists())
        self.assertEqual(self.d.downloads,1)
