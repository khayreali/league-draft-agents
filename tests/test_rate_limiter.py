import asyncio
import time

import pytest

from draft_analyst.data.rate_limiter import TokenBucket, RiotRateLimiter


@pytest.mark.asyncio
async def test_token_bucket_basic():
    bucket = TokenBucket(rate=5, period=1.0)
    # should be able to acquire 5 tokens immediately
    for _ in range(5):
        await bucket.acquire()
    assert bucket.tokens < 1


@pytest.mark.asyncio
async def test_token_bucket_refills():
    bucket = TokenBucket(rate=10, period=1.0)
    for _ in range(10):
        await bucket.acquire()

    # wait a bit for refill
    await asyncio.sleep(0.15)
    # should have ~1-2 tokens back
    await bucket.acquire()  # shouldn't block much


@pytest.mark.asyncio
async def test_riot_rate_limiter_doesnt_deadlock():
    """Make sure dual-bucket acquire doesn't hang."""
    limiter = RiotRateLimiter(per_second=5, per_2min=20)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # 5 requests with 5/sec limit should be nearly instant
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_token_bucket_waits_when_empty():
    bucket = TokenBucket(rate=2, period=1.0)
    await bucket.acquire()
    await bucket.acquire()
    # bucket is empty, next acquire should take ~0.5s
    start = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed > 0.1  # had to wait for refill
