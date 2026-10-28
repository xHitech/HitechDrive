import threading
import time
import unittest
from bandwidth import BandwidthLimiter
from drive import Paused
import test_http

class BandwidthTests(unittest.TestCase):
    def test_unlimited_does_not_wait(self):
        limiter=BandwidthLimiter(0)
        start=time.monotonic()
        limiter.acquire(1024**4,lambda:None)
        self.assertLess(time.monotonic()-start,.2)
    def test_parallel_workers_share_one_budget(self):
        limiter=BandwidthLimiter(1)
        start=time.monotonic()
        workers=[threading.Thread(target=limiter.acquire,args=(64*1024,lambda:None)) for _ in range(4)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(5)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertGreaterEqual(time.monotonic()-start,.24)  # 256 KiB / 1 MiB/s, shared rather than per-worker.
    def test_live_unlimited_wakes_waiter(self):
        limiter=BandwidthLimiter(.001)
        entered=threading.Event()
        worker=threading.Thread(target=limiter.acquire,args=(1024*1024,entered.set),daemon=True)
        worker.start();self.assertTrue(entered.wait(1))
        limiter.set_limit(0)
        worker.join(1);self.assertFalse(worker.is_alive())
    def test_pause_interrupts_wait(self):
        limiter=BandwidthLimiter(.001)
        count=[0]
        def check():
            count[0]+=1
            if count[0]>1:raise Paused()
        with self.assertRaises(Paused):limiter.acquire(1024*1024,check)
    def test_invalid_limits(self):
        for value in (-1,10001,float('nan'),float('inf'),True,'invalid'):
            with self.assertRaises((ValueError,TypeError)):BandwidthLimiter(value)

class BandwidthHttpTests(unittest.TestCase):
    setUp=test_http.HttpTests.setUp
    call=test_http.HttpTests.call
    def test_update_while_running_persists_and_is_reported(self):
        from drive import load_json
        e=self.server.engine;e.config['paused']=False;e.status['phase']='baixando'
        code,_,_=self.call('POST','/api/bandwidth',{'bandwidth_mib':15.5})
        self.assertEqual(code,200)
        self.assertEqual(e.bandwidth.rate,15.5*1024*1024)
        self.assertEqual(e.snapshot()['bandwidth_mib'],15.5)
        self.assertEqual(load_json(e.state/'config.json')['bandwidth_mib'],15.5)
        self.assertFalse(e.config['paused'])
        from engine import Engine
        restored=Engine(e.state,e.destination,guard=lambda:None)
        self.assertEqual(restored.bandwidth.rate,e.bandwidth.rate)
    def test_invalid_request_does_not_change_saved_limit(self):
        self.server.engine.set_bandwidth(10)
        self.assertEqual(self.call('POST','/api/bandwidth',{'bandwidth_mib':-1})[0],400)
        self.assertEqual(self.server.engine.snapshot()['bandwidth_mib'],10)
