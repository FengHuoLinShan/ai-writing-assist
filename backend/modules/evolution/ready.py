"""Run ready independent work; settle peers before propagating an unknown failure."""

import asyncio

from infrastructure.llm.limits import request_admission_scope


async def drain_ready(jobs, parallelism):
    if type(parallelism) is not int or parallelism < 1:
        raise ValueError("parallelism must be a positive integer")
    stop = asyncio.Event()
    pending = iter(jobs)

    async def worker():
        while not stop.is_set():
            job = next(pending, None)
            if job is None:
                return
            try:
                await job()
            except BaseException:
                stop.set()
                raise

    with request_admission_scope(stop):
        peers = asyncio.gather(
            *(worker() for _ in range(parallelism)), return_exceptions=True
        )
    try:
        results = await asyncio.shield(peers)
    except asyncio.CancelledError:
        stop.set()
        await peers
        raise
    for result in results:
        if isinstance(result, BaseException):
            raise result
