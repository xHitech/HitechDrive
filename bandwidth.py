"""Shared token bucket for every download, with live reconfiguration."""
import math
import threading
import time

class BandwidthLimiter:
    def __init__(self, mib_per_second=0):
        self.condition = threading.Condition()
        self.rate = 0
        self.tokens = 0
        self.updated = time.monotonic()
        self.set_limit(mib_per_second)

    @staticmethod
    def validate(value):
        if isinstance(value, bool):
            raise ValueError('Informe um número de MiB/s válido; 0 significa sem limite.')
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 10000:
            raise ValueError('O limite deve estar entre 0 e 10000 MiB/s; 0 significa sem limite.')
        return value

    def set_limit(self, value):
        value = self.validate(value)
        with self.condition:
            self.rate = value * 1024 * 1024
            self.tokens = 0
            self.updated = time.monotonic()
            self.condition.notify_all()

    def acquire(self, amount, check):
        remaining = amount
        while remaining > 0:
            check()
            with self.condition:
                if not self.rate:
                    return
                now = time.monotonic()
                # Small shared burst allowance; workers never receive separate bandwidth budgets.
                capacity = max(1, min(256 * 1024, self.rate * .1))
                self.tokens = min(capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                taken = min(remaining, self.tokens)
                self.tokens -= taken
                remaining -= taken
                if remaining > 0:
                    self.condition.wait(timeout=min(.1, remaining / self.rate))
