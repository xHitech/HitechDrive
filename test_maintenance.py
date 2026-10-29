import copy
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from drive import load_json,save_json
from engine import Engine
import test_mirror
import test_http

class MaintenanceTests(unittest.TestCase):
    setUp=test_mirror.MirrorTests.setUp
    def seed(self):
        self.d.items=[dict(test_mirror.item('a','book.cbz',content=b'book'),md5Checksum=hashlib.md5(b'book').hexdigest())]
        self.e.sync();self.e.config['paused']=True;self.e.status['phase']='pausado'
        self.e.expected_uuid='test-volume'
        save_json(self.e.state/'instance.json',{'volume_uuid':'test-volume','mountpoint':str(self.e.destination.parent),'destination':str(self.e.destination)})
        save_json(self.e.state/'account.json',{'permissionId':'test-owner','emailAddress':'private-placeholder'})
        save_json(self.e.state/'tokens.json',{'refresh_token':'not-a-real-token'})
        save_json(self.e.state/'client.json',{'installed':{'client_secret':'not-a-real-secret'}})
    def wait(self):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            if self.e.maintenance.snapshot()['state']!='running' and not self.e.operation_lock.locked():return
            time.sleep(.01)
        self.fail('Maintenance did not finish')
    def test_thread_start_failure_releases_operation_lock(self):
        self.seed()
        with patch('maintenance.threading.Thread.start', side_effect=RuntimeError('start failed')):
            with self.assertRaises(RuntimeError): self.e.maintenance.start('audit', 0)
        self.assertFalse(self.e.operation_lock.locked())
        self.assertEqual(self.e.maintenance.snapshot()['state'], 'error')

    def test_report_write_failure_is_visible_and_releases_lock(self):
        self.seed()
        with patch('maintenance.save_json', side_effect=OSError('disk unavailable')):
            self.e.maintenance.start('audit', 0)
            self.wait()
        self.assertFalse(self.e.operation_lock.locked())
        self.assertEqual(self.e.maintenance.snapshot()['state'], 'error')
        self.assertIn('relatório', self.e.maintenance.snapshot()['error'])

    def test_alerts_expose_auth_storage_and_integrity_problems(self):
        self.seed()
        self.e.auth_error = 'Reconecte a conta.'
        self.e.maintenance.report = {'failed': 2}
        self.e.guard = lambda: (_ for _ in ()).throw(RuntimeError('Volume ausente.'))
        self.e.alert_cache = (0, [])
        kinds = {alert['kind'] for alert in self.e.collect_alerts()}
        self.assertTrue({'auth', 'storage', 'integrity'} <= kinds)

    def test_audit_confirms_and_detects_corruption_without_overwriting(self):
        self.seed();self.e.maintenance.start('audit',0);self.wait()
        self.assertEqual(self.e.maintenance.report['ok'],1)
        (self.e.destination/'book.cbz').write_bytes(b'bad!')
        self.e.maintenance.start('audit',0);self.wait()
        self.assertEqual(self.e.maintenance.report['failed'],1)
        self.assertEqual((self.e.destination/'book.cbz').read_bytes(),b'bad!')
    def test_backup_excludes_oauth_and_roundtrips_without_redownload(self):
        self.seed();backup=self.e.maintenance.export()
        serialized=__import__('json').dumps(backup)
        self.assertNotIn('not-a-real-token',serialized);self.assertNotIn('not-a-real-secret',serialized)
        self.assertNotIn('private-placeholder',serialized)
        fresh_state=self.e.state.parent/'fresh'
        save_json(fresh_state/'instance.json',load_json(self.e.state/'instance.json'))
        restored=Engine(fresh_state,self.e.destination,guard=lambda:None)
        restored.maintenance.restore(backup)
        self.assertTrue(restored.config['paused'])
        restored.drive=self.d;restored.config['paused']=False;restored.sync()
        self.assertEqual(self.d.downloads,1)
    def test_import_rejects_existing_manifest_wrong_volume_and_traversal(self):
        self.seed();backup=self.e.maintenance.export()
        with self.assertRaises(ValueError):self.e.maintenance.restore(backup)
        self.e.manifest={'files':{},'folders':[]}
        bad=copy.deepcopy(backup);bad['instance']['volume_uuid']='wrong'
        with self.assertRaises(ValueError):self.e.maintenance.restore(bad)
        bad=copy.deepcopy(backup);bad['manifest']['files']['a']['path']='../outside'
        with self.assertRaises(RuntimeError):self.e.maintenance.restore(bad)
        bad=copy.deepcopy(backup);bad['manifest']['files']['a']['path']='.drive-espelho/recovery.json'
        with self.assertRaises(ValueError):self.e.maintenance.restore(bad)
    def test_rebuild_adopts_only_verified_files(self):
        self.seed();self.e.manifest={'files':{},'folders':[]};self.e.persist()
        self.e.maintenance.start('rebuild',0);self.wait()
        self.assertEqual(self.e.maintenance.report['ok'],1)
        self.assertIn('a',self.e.manifest['files'])
        self.assertEqual(self.d.downloads,1)
        self.e.config['paused']=False;self.e.sync();self.assertEqual(self.d.downloads,1)
    def test_cleanup_requires_preview_phrase_and_preserves_modified_files(self):
        self.seed();trash=self.e.local('.drive-espelho/lixeira/old/file');trash.parent.mkdir(parents=True);trash.write_bytes(b'old')
        partial=self.e.local('.drive-espelho/parciais/test.part');partial.write_bytes(b'partial')
        preview=self.e.maintenance.cleanup_preview()
        self.assertEqual(preview['count'],2)
        with self.assertRaises(ValueError):self.e.maintenance.cleanup(preview['token'],'all','no')
        trash.write_bytes(b'changed-after-preview')
        result=self.e.maintenance.cleanup(preview['token'],'all','APAGAR DEFINITIVAMENTE')
        self.assertEqual(result,{'removed':1,'skipped':1})
        self.assertTrue(trash.exists());self.assertFalse(partial.exists())
        self.assertTrue((self.e.destination/'book.cbz').exists())
    def test_cleanup_does_not_follow_links_or_touch_checkpoint(self):
        self.seed();root=self.e.local('.drive-espelho/lixeira');root.mkdir(parents=True)
        outside=self.e.destination.parent/'outside';outside.write_bytes(b'keep')
        (root/'link').symlink_to(outside)
        checkpoint=self.e.local('.drive-espelho/recovery.json');checkpoint.write_text('{}')
        preview=self.e.maintenance.cleanup_preview()
        self.assertEqual(preview['count'],0)
        self.e.maintenance.cleanup(preview['token'],'all','APAGAR DEFINITIVAMENTE')
        self.assertEqual(outside.read_bytes(),b'keep');self.assertTrue(checkpoint.exists())
    def test_running_sync_and_maintenance_are_mutually_exclusive(self):
        self.seed();self.e.config['paused']=False
        with self.assertRaises(ValueError):self.e.maintenance.start('audit',0)
        self.e.config['paused']=True
        self.e.operation_lock.acquire()
        try:
            with self.assertRaises(ValueError):self.e.maintenance.start('audit',0)
        finally:self.e.operation_lock.release()
    def test_checkpoint_written_privately_after_successful_cycle(self):
        self.seed();self.e.config['paused']=False;self.e.sync()
        checkpoint=self.e.local('.drive-espelho/recovery.json')
        backup=load_json(checkpoint)
        self.assertEqual(backup['owner'],{'permissionId':'test-owner'})
        self.assertEqual(checkpoint.stat().st_mode&0o777,0o600)
        self.assertNotIn('tokens',str(backup.keys()))
    def test_cancelled_audit_releases_operation_lock(self):
        self.seed();entered=threading.Event();release=threading.Event()
        original=self.e.maintenance.digest
        def digest(*args):
            entered.set();release.wait(2);self.e.maintenance.check();return original(*args)
        with patch.object(self.e.maintenance,'digest',side_effect=digest):
            self.e.maintenance.start('audit',0);self.assertTrue(entered.wait(2))
            self.e.maintenance.cancelled.set();release.set();self.wait()
        self.assertEqual(self.e.maintenance.task['state'],'cancelled')
        self.assertFalse(self.e.operation_lock.locked())
    def test_interrupted_recovery_import_is_completed_on_startup(self):
        self.seed();backup=self.e.maintenance.export()
        other=self.e.state.parent/'other'
        documents={'account.json':backup['owner'],'config.json':backup['config'],'manifest.json':backup['manifest']}
        save_json(other/'recovery.pending.json',documents)
        save_json(other/'instance.json',backup['instance'])
        fresh=Engine(other,self.e.destination,guard=lambda:None)
        self.assertIn('a',fresh.manifest['files'])
        self.assertFalse((other/'recovery.pending.json').exists())

class MaintenanceHttpTests(unittest.TestCase):
    setUp=test_http.HttpTests.setUp
    call=test_http.HttpTests.call
    def test_routes_asset_and_bad_cleanup_confirmation(self):
        self.assertEqual(self.call('GET','/maintenance.js')[0],200)
        self.assertEqual(self.call('POST','/api/cleanup-confirm',{'token':'none','kind':'all','confirmation':'no'})[0],400)
        self.assertEqual(self.call('POST','/api/maintenance-start',{'kind':'invalid'})[0],400)
