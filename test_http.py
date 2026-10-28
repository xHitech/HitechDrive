"""Exercise real HTTP handlers without network sockets (sandbox blocks sockets)."""
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from app import Handler
from engine import Engine

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        e=Engine(Path(self.tmp.name)/'state',Path(self.tmp.name)/'media',guard=lambda:None)
        self.server=SimpleNamespace(server_port=8765,engine=e,csrf='test-secret',auth_lock=threading.Lock())
    def call(self,method,path,body=None,host='127.0.0.1:8765',origin='http://127.0.0.1:8765',csrf='test-secret'):
        h=object.__new__(Handler);h.server=self.server;h.path=path
        h.command=method;h.request_version='HTTP/1.1';h.requestline=f'{method} {path} HTTP/1.1'
        h.headers=Message();h.headers['Host']=host;h.headers['Origin']=origin;h.headers['X-CSRF-Token']=csrf
        raw=json.dumps(body or {}).encode();h.headers['Content-Length']=str(len(raw))
        h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO()
        getattr(h,'do_'+method)()
        response=h.wfile.getvalue();head,data=response.split(b'\r\n\r\n',1)
        return int(head.split()[1]),data,head
    def test_dashboard_assets_and_status(self):
        for path in ('/','/ui.js','/style.css','/api/status'):
            code,data,head=self.call('GET',path)
            self.assertEqual(code,200);self.assertTrue(data)
            self.assertIn(b'X-Frame-Options: DENY',head)
        status=json.loads(self.call('GET','/api/status')[1])
        self.assertEqual(status['csrf'],'test-secret');self.assertFalse(status['connected'])
    def test_foreign_host_rejected(self):
        self.assertEqual(self.call('GET','/api/status',host='evil.example:8765')[0],403)
    def test_foreign_origin_rejected(self):
        self.assertEqual(self.call('POST','/api/settings',origin='https://evil.example')[0],403)
    def test_missing_csrf_rejected(self):
        self.assertEqual(self.call('POST','/api/pause',csrf='')[0],403)
    def test_start_requires_google_connection(self):
        self.assertEqual(self.call('POST','/api/start')[0],400)
        self.assertTrue(self.server.engine.config['paused'])
    def test_import_desktop_credentials_private(self):
        code,_,_=self.call('POST','/api/client',{'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'example'}})
        self.assertEqual(code,200)
        self.assertEqual((self.server.engine.state/'client.json').stat().st_mode&0o777,0o600)
    def test_web_credentials_rejected(self):
        self.assertEqual(self.call('POST','/api/client',{'web':{'client_id':'bad'}})[0],400)
    def test_folder_link_settings(self):
        code,_,_=self.call('POST','/api/settings',{'root':'https://drive.google.com/drive/folders/folder123?usp=sharing','interval':60})
        self.assertEqual(code,200);self.assertEqual(self.server.engine.config['root'],'folder123')
    def test_callback_missing_state_never_connects(self):
        code,_,_=self.call('GET','/oauth/callback?code=invalid')
        self.assertEqual(code,400);self.assertFalse((self.server.engine.state/'tokens.json').exists())
