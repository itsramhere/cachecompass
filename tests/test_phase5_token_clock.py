"""Token rate changes must not mint credit before their recorded start."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cache_scaleout.migration import TokenBuckets

class ClockLinearization(unittest.TestCase):
    def test_rate_change_and_acquisition_credit_share_one_clock_boundary(self):
        class Clock:
            value=0
            def __call__(self):
                at=self.value;self.value+=1_000_000;return at
        clock=Clock();b=TokenBuckets({'operations':0.},{'operations':100},clock=clock)
        b.set_rates({'operations':100.})
        start=b.events[-1]['at_ns'];b.refill()
        expected=min(100,100*(b.updated-start)/1e9)
        self.assertAlmostEqual(b.tokens['operations'],expected,places=10)
