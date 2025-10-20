import asyncio
import time


class TokenBucket:
    """Simple token bucket — used for Riot's per-second and per-2-min limits."""

    def __init__(self, rate: int, period: float):
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed * (self.rate / self.period)
        self.tokens = min(self.rate, self.tokens + new_tokens)
        self.last_refill = now

    async def acquire(self):
        async with self._lock:
            self._refill()
            if self.tokens < 1:
                wait = (1 - self.tokens) * (self.period / self.rate)
                await asyncio.sleep(wait)
                self._refill()
            self.tokens -= 1


class RiotRateLimiter:
    """Dual bucket for Riot's two rate limit windows."""

    def __init__(self, per_second: int = 20, per_2min: int = 100):
        self.short = TokenBucket(per_second, 1.0)
        self.long = TokenBucket(per_2min, 120.0)

    async def acquire(self):
        # need to satisfy both limits
        await self.short.acquire()
        await self.long.acquire()
