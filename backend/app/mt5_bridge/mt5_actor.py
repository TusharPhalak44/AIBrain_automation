"""Thread-Safe Priority MT5 Actor.

Routes all MetaTrader 5 API calls through a dedicated single-worker ThreadPoolExecutor
with prioritized execution to prevent DLL concurrency deadlocks:
- Priority 0 (P0_EMERGENCY): Emergency panic flatten, hard SL attachment, kill switch.
- Priority 1 (P1_POSITIONS): Trade entries, partial TP closures, position queries.
- Priority 2 (P2_QUOTES_HISTORY): Ticks, symbol specs, historical bars.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PriorityLevel(IntEnum):
    P0_EMERGENCY = 0
    P1_POSITIONS = 1
    P2_QUOTES_HISTORY = 2


class MT5Actor:
    """Thread-safe sequential actor executing all MT5 DLL operations."""

    def __init__(self):
        # Strictly max_workers=1 for MT5 Windows IPC thread affinity
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="MT5Worker")
        self._queue: Optional[asyncio.PriorityQueue] = None
        self._running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """Start async priority queue processor on current event loop."""
        curr_loop = asyncio.get_running_loop()
        if self._loop != curr_loop or not self._running or self._worker_task is None or self._worker_task.done():
            self._loop = curr_loop
            self._queue = asyncio.PriorityQueue()
            self._running = True
            self._worker_task = curr_loop.create_task(self._process_queue())
            logger.info("MT5 Actor started on current event loop.")

    async def stop(self) -> None:
        """Stop actor and shutdown worker thread pool."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        self._executor.shutdown(wait=True)
        logger.info("MT5 Actor stopped.")

    async def _process_queue(self) -> None:
        while self._running:
            try:
                if self._queue is None:
                    break
                priority, task_id, func, args, kwargs, future = await self._queue.get()
                loop = asyncio.get_running_loop()
                try:
                    res = await loop.run_in_executor(self._executor, func, *args, **kwargs)
                    if not future.done():
                        future.set_result(res)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in MT5 Actor worker loop: {e}")

    async def execute(
        self,
        priority: PriorityLevel,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Submit a callable to the prioritized MT5 execution queue."""
        loop = asyncio.get_running_loop()
        if self._loop != loop or not self._running or self._worker_task is None or self._worker_task.done():
            await self.start()
        future: asyncio.Future = loop.create_future()
        # Task ID ensures deterministic FIFO ordering within the same priority level
        task_id = id(future)
        await self._queue.put((int(priority), task_id, func, args, kwargs, future))
        return await future

    # Convenience shortcuts
    async def run_emergency(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return await self.execute(PriorityLevel.P0_EMERGENCY, func, *args, **kwargs)

    async def run_position(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return await self.execute(PriorityLevel.P1_POSITIONS, func, *args, **kwargs)

    async def run_quote(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return await self.execute(PriorityLevel.P2_QUOTES_HISTORY, func, *args, **kwargs)


mt5_actor = MT5Actor()

