from collections import deque
import hashlib
import threading
import time
import unittest
from unittest.mock import patch

from drive import load_json, Paused, save_json
from engine import Engine, fingerprint, RESERVED
import test_mirror
import test_http

class ProgressTests(unittest.TestCase):
    setUp=test_mirror.MirrorTests.setUp

    def test_completed_files_count_bytes_without_downloading_again(self):
        self.d.items=[test_mirror.item(content=b'abc'),test_mirror.item('b','b.cbz',content=b'abcdef')]
        self.e.sync();s=self.e.snapshot()
        self.assertEqual((s['total_bytes'],s['copied_bytes'],s['remaining_bytes']),(9,9,0))
        self.e.sync();self.assertEqual(self.d.downloads,2)
        restored=Engine(self.e.state,self.e.destination,guard=lambda:None)
        self.assertEqual(restored.snapshot()['last_sync'],s['last_sync'])

    def test_resumed_partial_is_not_double_counted(self):
        meta=dict(test_mirror.item(content=b'abcdef'),relative='filme.mkv')
        self.e.destination.mkdir()
        work=self.e.local(RESERVED+'/parciais');work.mkdir(parents=True)
        key=hashlib.sha256((meta['id']+fingerprint(meta)).encode()).hexdigest()
        (work/(key+'.part')).write_bytes(b'abc')
        self.e.prepare_progress({'a':meta})
        self.assertEqual(self.e.snapshot()['copied_bytes'],3)
        self.e.update_bytes('a',5);self.e.update_bytes('a',5)
        self.assertEqual(self.e.snapshot()['copied_bytes'],5)
        self.e.update_bytes('a',99)
        self.assertEqual(self.e.snapshot()['copied_bytes'],6)
        self.e.update_bytes('a',0)
        self.assertEqual(self.e.snapshot()['remaining_bytes'],6)

    def test_failures_persist_and_clear_only_after_success(self):
        self.d.items=[test_mirror.item()];self.d.fail_download=True
        with self.assertRaises(RuntimeError):self.e.sync()
        self.assertEqual(self.e.snapshot()['error_count'],1)
        restored=Engine(self.e.state,self.e.destination,guard=lambda:None)
        self.assertEqual(restored.snapshot()['errors'][0]['name'],'filme.mkv')
        with self.assertRaises(RuntimeError):self.e.sync()
        self.assertEqual(self.e.snapshot()['errors'][0]['attempts'],2)
        self.d.fail_download=False;self.e.sync()
        self.assertEqual(self.e.snapshot()['error_count'],0)
        self.assertEqual(load_json(self.e.state/'errors.json'),{})

    def test_unknown_export_size_excluded_from_byte_total(self):
        self.d.items=[dict(test_mirror.item(),mimeType='application/vnd.google-apps.form')]
        self.e.sync();s=self.e.snapshot()
        self.assertEqual(s['total_bytes'],0)
        self.assertEqual(s['unknown_size_files'],1)

    def test_eta_uses_recent_network_bytes_and_stops_when_paused(self):
        self.e.status.update(phase='baixando',total_bytes=1000,copied_bytes=400)
        self.e.network_bytes=200
        self.e.rate_samples=deque([(90,0),(95,100)])
        with patch('engine.time.monotonic',return_value=100):
            self.assertEqual(self.e.snapshot()['overall_speed'],20)
            self.assertEqual(self.e.snapshot()['eta_seconds'],30)
            self.e.config['paused']=True
            self.assertIsNone(self.e.snapshot()['eta_seconds'])

    def test_pause_is_not_recorded_as_download_error(self):
        self.d.items=[test_mirror.item()]
        def download(*args):raise Paused()
        self.d.download=download
        with self.assertRaises(Paused):self.e.sync()
        self.assertEqual(self.e.snapshot()['error_count'],0)

    def test_retry_retains_bandwidth_and_refuses_active_cycle(self):
        self.e.failures={'a':{'id':'a','name':'x','message':'x','attempts':1,'time':'now'}}
        self.e.set_bandwidth(12)
        self.e.status['phase']='baixando'
        with self.assertRaises(ValueError):self.e.retry_errors()
        self.e.status['phase']='erro';self.e.config['paused']=True
        self.e.retry_errors()
        self.assertFalse(self.e.config['paused']);self.assertTrue(self.e.wake.is_set())
        self.assertEqual(self.e.config['bandwidth_mib'],12)

    def test_removed_remote_file_clears_stale_error(self):
        self.d.items=[test_mirror.item()];self.d.fail_download=True
        with self.assertRaises(RuntimeError):self.e.sync()
        self.d.items=[];self.e.sync()
        self.assertEqual(self.e.snapshot()['error_count'],0)

class RetryHttpTests(unittest.TestCase):
    setUp=test_http.HttpTests.setUp
    call=test_http.HttpTests.call
    def test_retry_requires_connection_then_wakes_worker(self):
        self.assertEqual(self.call('POST','/api/retry-errors')[0],400)
        e=self.server.engine
        save_json(e.state/'tokens.json',{'fake':'test'});save_json(e.state/'account.json',{'fake':'test'})
        e.failures={'a':{'id':'a','name':'x','message':'failed','attempts':1,'time':'now'}}
        self.assertEqual(self.call('POST','/api/retry-errors')[0],200)
        self.assertTrue(e.wake.is_set())
