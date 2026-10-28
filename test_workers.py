import threading
import unittest
from drive import load_json
import test_mirror
import test_http

class LiveWorkersTests(unittest.TestCase):
    setUp=test_mirror.MirrorTests.setUp

    def run_controlled_queue(self,initial):
        self.e.set_workers(initial)
        gates={str(i):threading.Event() for i in range(6)}
        started={str(i):threading.Event() for i in range(6)}
        errors=[]
        def transfer(fid,item):
            started[fid].set()
            if not gates[fid].wait(5):raise RuntimeError('test gate timed out')
        self.e.transfer=transfer
        files={str(i):{'id':str(i),'relative':str(i)} for i in range(6)}
        def run():
            try:self.e.download_all(files)
            except BaseException as exc:errors.append(exc)
        worker=threading.Thread(target=run)
        worker.start()
        def cleanup():
            for gate in gates.values():gate.set()
            worker.join(3)
        self.addCleanup(cleanup)
        return gates,started,worker,errors

    def test_reduce_to_one_waits_for_existing_and_stops_replenishing(self):
        gates,started,worker,errors=self.run_controlled_queue(3)
        for fid in ('0','1','2'):self.assertTrue(started[fid].wait(2))
        self.e.set_workers(1)
        gates['0'].set()
        self.assertFalse(started['3'].wait(.15))
        gates['1'].set()
        self.assertFalse(started['3'].wait(.15))
        gates['2'].set()
        self.assertTrue(started['3'].wait(2))
        self.assertFalse(started['4'].is_set())
        gates['3'].set();self.assertTrue(started['4'].wait(2))
        gates['4'].set();self.assertTrue(started['5'].wait(2))
        gates['5'].set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(load_json(self.e.state/'config.json')['workers'],1)

    def test_increase_opens_slots_during_current_cycle(self):
        gates,started,worker,errors=self.run_controlled_queue(1)
        self.assertTrue(started['0'].wait(2));self.assertFalse(started['1'].is_set())
        self.e.set_workers(3)
        self.assertTrue(started['1'].wait(2));self.assertTrue(started['2'].wait(2))
        self.assertFalse(started['3'].is_set())
        for gate in gates.values():gate.set()
        worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(errors,[])

    def test_invalid_counts_do_not_change_configuration(self):
        self.e.set_workers(2)
        for count in (0,9,True,1.5,None,'oops'):
            with self.assertRaises(ValueError):self.e.set_workers(count)
        self.assertEqual(self.e.snapshot()['workers'],2)
        self.assertTrue(self.e.snapshot()['workers_live'])

class LiveWorkersHttpTests(unittest.TestCase):
    setUp=test_http.HttpTests.setUp
    call=test_http.HttpTests.call
    def test_applies_while_running_without_pausing(self):
        e=self.server.engine;e.config['paused']=False;e.status['phase']='baixando'
        self.assertEqual(self.call('POST','/api/workers',{'workers':1})[0],200)
        self.assertEqual(e.config['workers'],1);self.assertFalse(e.config['paused'])
        e.active={'a':{},'b':{}}
        self.assertEqual(e.snapshot()['workers_draining'],1)
        self.assertEqual(self.call('POST','/api/workers',{'workers':0})[0],400)
