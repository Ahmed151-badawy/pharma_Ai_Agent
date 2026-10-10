import time

from app.ratelimit import SlidingWindowLimiter


def test_allows_up_to_limit_then_blocks_then_recovers():
    limiter = SlidingWindowLimiter()
    assert limiter.check("k", 2, 0.3) == 0
    assert limiter.check("k", 2, 0.3) == 0
    assert limiter.check("k", 2, 0.3) > 0
    time.sleep(0.35)
    assert limiter.check("k", 2, 0.3) == 0


def test_keys_are_independent():
    limiter = SlidingWindowLimiter()
    assert limiter.check("a", 1) == 0
    assert limiter.check("b", 1) == 0
    assert limiter.check("a", 1) > 0
