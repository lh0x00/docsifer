import asyncio

import pytest

from docsifer.exceptions import (
    CircuitOpenError,
    QueueFullError,
    TooManyRequestsError,
)
from docsifer.safety.circuit_breaker import CircuitBreaker
from docsifer.safety.conversion_gate import ConversionGate
from docsifer.safety.per_ip_limiter import PerIPLimiter


@pytest.mark.asyncio
async def test_conversion_gate_admits_up_to_max() -> None:
    gate = ConversionGate(max_concurrent=2, max_queue=0)

    async def _job() -> None:
        async with gate.acquire():
            await asyncio.sleep(0.05)

    await asyncio.gather(_job(), _job())  # OK, capacity = 2


@pytest.mark.asyncio
async def test_conversion_gate_rejects_when_queue_full() -> None:
    gate = ConversionGate(max_concurrent=1, max_queue=0)

    async with gate.acquire():
        with pytest.raises(QueueFullError):
            async with gate.acquire():
                pass


@pytest.mark.asyncio
async def test_per_ip_limiter() -> None:
    lim = PerIPLimiter(max_per_ip=1)
    async with lim.acquire("1.2.3.4"):
        with pytest.raises(TooManyRequestsError):
            async with lim.acquire("1.2.3.4"):
                pass
    # Same IP can acquire again after release
    async with lim.acquire("1.2.3.4"):
        pass


@pytest.mark.asyncio
async def test_circuit_breaker_opens_on_failures() -> None:
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_sec=60)

    async def _bad() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(_bad)
    with pytest.raises(RuntimeError):
        await cb.call(_bad)
    with pytest.raises(CircuitOpenError):
        await cb.call(_bad)
    assert cb.state == "open"
