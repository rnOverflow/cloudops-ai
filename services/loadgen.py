"""Steady synthetic traffic against the demo api-gateway (docker-compose profile `services`).

Open-loop arrivals at RPS, with a hard cap on in-flight requests: when the target is
slow, new arrivals are dropped (and counted) instead of piling up without bound, which
would otherwise turn a slowdown into a self-inflicted overload spiral.
"""

import asyncio
import os
import random

import httpx

TARGET = os.environ.get("TARGET", "http://api-gateway:8080/api/work")
RPS = float(os.environ.get("RPS", "10"))
MAX_IN_FLIGHT = int(os.environ.get("MAX_IN_FLIGHT", "20"))


async def main() -> None:
    sem = asyncio.Semaphore(MAX_IN_FLIGHT)
    stats = {"sent": 0, "dropped": 0, "errors": 0}

    async def one(client: httpx.AsyncClient) -> None:
        try:
            r = await client.get(TARGET)
            if r.status_code >= 500:
                stats["errors"] += 1
        except httpx.HTTPError:
            stats["errors"] += 1
        finally:
            sem.release()

    async def report() -> None:
        while True:
            await asyncio.sleep(30)
            print(f'{{"event":"loadgen_stats","sent":{stats["sent"]},"dropped":{stats["dropped"]},"errors":{stats["errors"]}}}', flush=True)

    async with httpx.AsyncClient(timeout=5.0, limits=httpx.Limits(max_connections=MAX_IN_FLIGHT)) as client:
        asyncio.create_task(report())
        while True:
            if sem.locked():
                stats["dropped"] += 1
            else:
                await sem.acquire()
                stats["sent"] += 1
                asyncio.create_task(one(client))
            await asyncio.sleep(random.expovariate(RPS))


if __name__ == "__main__":
    asyncio.run(main())
