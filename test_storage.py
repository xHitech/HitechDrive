import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from drive import Drive, load_json, save_json
from engine import Engine
from test_mirror import Response
import test_http

class StorageConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/'state'
        self.mountpoint=self.root/'volume'
        self.destination=self.mountpoint/'GoogleDrive'
    def configure(self):
        save_json(self.state/'instance.json',{'mountpoint':str(self.mountpoint),'destination':str(self.destination),'volume_uuid':'test-volume-id'})
    def test_unconfigured_volume_is_blocked(self):
        e=Engine(self.state)
        with self.assertRaisesRegex(RuntimeError,'Configure o volume'):e.mount_guard()
    def test_private_config_used_and_expected_volume_checked(self):
        self.configure();e=Engine(self.state)
        self.assertEqual(e.destination,self.destination)
        with patch('engine.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='test-volume-id\n')) as run:
            e.mount_guard()
            self.assertEqual(run.call_args.args[0][-1],str(self.mountpoint))
        self.assertFalse(self.destination.exists())
    def test_wrong_volume_and_destination_outside_mount_are_blocked(self):
        self.configure();e=Engine(self.state)
        with patch('engine.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='other-volume\n')):
            with self.assertRaises(RuntimeError):e.mount_guard()
        e.destination=self.root/'outside'
        with self.assertRaisesRegex(RuntimeError,'subpasta'):e.mount_guard()
    def test_short_export_never_returns_success(self):
        drive=Drive(self.state);drive.json=lambda *args:{'version':'1'}
        item={'id':'fake-document','mimeType':'application/vnd.google-apps.document','version':'1'}
        with patch.object(drive,'request',return_value=Response(b'short',200,{'Content-Length':'100'})):
            with self.assertRaisesRegex(RuntimeError,'Transferência incompleta'):
                drive.download(item,self.root/'doc.part',lambda *a:None,lambda:None)

class ThemeAssetTests(unittest.TestCase):
    setUp=test_http.HttpTests.setUp
    call=test_http.HttpTests.call
    def test_theme_asset_served_and_link_present(self):
        self.assertEqual(self.call('GET','/theme.js')[0],200)
        html=self.call('GET','/')[1].decode()
        self.assertIn('id="theme-toggle"',html)
        self.assertIn('https://github.com/xHitech',html)
