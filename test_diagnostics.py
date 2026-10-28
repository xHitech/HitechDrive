from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from diagnostics import Diagnostics, disk_delta
import test_http

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.sys=self.root/'sys';self.proc=self.root/'proc'
        self.context={'network_bytes':0,'internet_mbps':100,'bandwidth_mib':0}
        self.d=Diagnostics(lambda:dict(self.context),self.sys,self.proc)
        self.put(self.sys/'block/md127/md/level','raid10')
        self.put(self.sys/'block/md127/md/degraded','0')
        self.put(self.sys/'block/md127/md/sync_action','idle')
        self.put(self.sys/'block/md127/md/array_state','active')
        self.put(self.sys/'block/sda/sda1/partition','1')
        self.put(self.sys/'block/sda/device/model','test disk')
        slaves=self.sys/'block/md127/slaves';slaves.mkdir()
        (slaves/'sda1').symlink_to(self.sys/'block/sda/sda1')
        (self.sys/'class/net/eth0/device').mkdir(parents=True)
        self.put(self.sys/'class/net/eth0/operstate','up')
        self.put(self.sys/'class/net/eth0/speed','1000')
        self.put(self.proc/'pressure/io','some avg10=15.00 avg60=0 avg300=0 total=0\nfull avg10=5 avg60=0 avg300=0 total=0')
        self.put(self.proc/'meminfo','Dirty: 100 kB\nWriteback: 20 kB')
    def put(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
    def sample(self,n):
        stat=[0]*17
        stat[4]=n*10;stat[6]=n*4096;stat[7]=n*1000;stat[9]=n*2000;stat[10]=n*6000
        self.put(self.sys/'block/sda/stat',' '.join(map(str,stat)))
        self.put(self.sys/'class/net/eth0/statistics/rx_bytes',str(n*25000000))
        self.put(self.sys/'class/net/eth0/statistics/tx_bytes',str(n*100000))
        self.context['network_bytes']=n*20000000
        self.d.observe('receive',1);self.d.observe('write',.1)
        with patch('diagnostics.time.monotonic',return_value=n*2):return self.d.snapshot()
    def test_rates_and_first_sample_unavailable(self):
        first=self.sample(0)
        self.assertTrue(first['warming_up']);self.assertIsNone(first['current']['disks'][0]['metrics'])
        result=self.sample(1);m=result['current']['disks'][0]['metrics']
        self.assertEqual(m['busy_pct'],100)
        self.assertEqual(m['write_bps'],1048576)
        self.assertEqual(m['await_ms'],100)
        self.assertEqual(m['queue'],3)
        self.assertEqual(result['current']['internet_pct'],100)
        self.assertEqual(result['current']['google_bps'],10000000)
        self.assertAlmostEqual(sum(result['current']['stages_pct'].values()),100)
    def test_sustained_bottleneck_requires_three_intervals(self):
        self.sample(0);self.sample(1)
        result=self.sample(2)
        self.assertFalse(any('gargalo no HD' in w for w in result['warnings']))
        result=self.sample(3)
        self.assertTrue(any('gargalo no HD sda' in w for w in result['warnings']))
        self.assertTrue(any('plano informado' in w for w in result['warnings']))
    def test_unknown_plan_never_invents_percent(self):
        self.context['internet_mbps']=0
        self.sample(0);result=self.sample(1)
        self.assertIsNone(result['current']['internet_pct'])
    def test_counter_reset_not_treated_as_negative_rate(self):
        self.assertIsNone(disk_delta([100]*17,[0]*17,1))
    def test_degraded_raid_warns_immediately(self):
        self.put(self.sys/'block/md127/md/degraded','1')
        result=self.sample(0)
        self.assertTrue(any('RAID degradado' in w for w in result['warnings']))
    def test_missing_sysfs_is_explicit(self):
        d=Diagnostics(lambda:{},self.root/'missing',self.proc)
        self.assertFalse(d.snapshot()['available'])

class DiagnosticsHttpTests(unittest.TestCase):
    setUp=test_http.HttpTests.setUp
    call=test_http.HttpTests.call
    def test_settings_persist_while_downloading(self):
        from drive import load_json
        e=self.server.engine;e.config['paused']=False;e.status['phase']='baixando'
        self.assertEqual(self.call('POST','/api/diagnostics-settings',{'internet_mbps':500})[0],200)
        self.assertEqual(load_json(e.state/'config.json')['internet_mbps'],500)
        self.assertEqual(self.call('POST','/api/diagnostics-settings',{'internet_mbps':-1})[0],400)
    def test_graph_js_served(self):
        self.assertEqual(self.call('GET','/diagnostics.js')[0],200)
