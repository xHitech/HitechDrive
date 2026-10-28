import tempfile
from pathlib import Path
import unittest
import urllib.error
from drive import Drive, FOLDER, load_json, save_json, Paused
from engine import Engine

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)/'state'; self.state.mkdir()
        self.drive = Drive(self.state)
        self.calls = []
    def catalog(self):
        return self.drive.catalog(lambda:None, lambda message:None)
    def test_initial_paginated_listing_then_changes_and_cached_next_cycle(self):
        def request(endpoint, params=None):
            self.calls.append((endpoint, params))
            if endpoint=='changes/startPageToken': return {'startPageToken':'before'}
            if endpoint=='files':
                if params.get('pageToken')=='second': return {'files':[{'id':'b','name':'B','parents':['root']}]}
                return {'nextPageToken':'second','files':[{'id':'a','name':'old','parents':['root']}]}
            if params['pageToken']=='before':
                return {'newStartPageToken':'after','changes':[{'fileId':'a','file':{'id':'a','name':'new','parents':['root']}}]}
            return {'newStartPageToken':'next','changes':[]}
        self.drive.json=request
        self.assertEqual(self.catalog()['a']['name'],'new')
        self.assertEqual(len([c for c in self.calls if c[0]=='files']),2)
        self.calls.clear();self.catalog()
        self.assertEqual([c[0] for c in self.calls],['changes'])
        self.assertEqual(self.calls[0][1]['pageToken'],'after')
    def test_partial_change_failure_keeps_old_cache_and_cursor(self):
        original={'cursor':'start','items':{'a':{'id':'a'}}}; save_json(self.state/'catalog.json',original)
        def request(endpoint, params):
            if params['pageToken']=='start': return {'nextPageToken':'page2','changes':[{'fileId':'a','removed':True}]}
            raise RuntimeError('network failure')
        self.drive.json=request
        with self.assertRaises(RuntimeError):self.catalog()
        self.assertEqual(load_json(self.state/'catalog.json'), original)
    def test_removals_and_trashed_items(self):
        save_json(self.state/'catalog.json',{'cursor':'start','items':{'a':{'id':'a'},'b':{'id':'b'},'c':{'id':'c'}}})
        self.drive.json=lambda *a:{'newStartPageToken':'next','changes':[
            {'fileId':'a','removed':True}, {'fileId':'b','file':{'id':'b','trashed':True}}]}
        self.assertEqual(set(self.catalog()),{'c'})
    def test_incomplete_initial_search_never_commits(self):
        self.drive.json=lambda endpoint,params=None: {'startPageToken':'start'} if endpoint=='changes/startPageToken' else {'incompleteSearch':True,'files':[]}
        with self.assertRaises(RuntimeError):self.catalog()
        self.assertFalse((self.state/'catalog.json').exists())
    def test_expired_cursor_rebuilds(self):
        save_json(self.state/'catalog.json',{'cursor':'expired','items':{'old':{'id':'old'}}})
        def request(endpoint,params=None):
            if endpoint=='changes' and params['pageToken']=='expired':
                error=urllib.error.HTTPError('https://google',410,'expired',{},None)
                error.close()
                raise RuntimeError('expired') from error
            if endpoint=='changes/startPageToken':return {'startPageToken':'new'}
            if endpoint=='files':return {'files':[{'id':'fresh'}]}
            return {'changes':[],'newStartPageToken':'saved'}
        self.drive.json=request
        self.assertEqual(set(self.catalog()),{'fresh'})
    def test_reconstruct_tree_and_exclude_shared_outside_root(self):
        e=Engine(self.state,Path(self.tmp.name)/'media',guard=lambda:None);e.config['paused']=False
        e.drive.json=lambda *a:{'id':'actual-root','mimeType':FOLDER}
        e.drive.catalog=lambda *a:{'dir':{'id':'dir','name':'Books','mimeType':FOLDER,'parents':['actual-root']},
            'book':{'id':'book','name':'book.cbz','mimeType':'application/zip','parents':['dir']},
            'shared':{'id':'shared','name':'outside','mimeType':'text/plain','parents':['someone-else']}}
        files,folders=e.scan()
        self.assertEqual(set(files),{'book'});self.assertEqual(files['book']['relative'],'Books/book.cbz')
        self.assertEqual(folders,['Books'])
