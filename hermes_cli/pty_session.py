"""Keep-alive PTY sessions for dashboard terminals.

A PTY process outlives the WebSocket that created it: a single drain task
always reads the PTY into a bounded RingBuffer and forwards to the attached
socket when present. Reconnecting with the same opaque token replays the
buffer and resumes live. See
docs/superpowers/specs/2026-06-20-pty-keepalive-reattach-design.md.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

WS_CLOSE_PROCESS_EXITED = 4410
WS_CLOSE_SUPERSEDED = 4409


class RingBuffer:
    """Keeps only the most recent ``capacity`` bytes appended to it."""

    def __init__(self, capacity: int) -> None:
        self._cap = capacity
        self._buf = bytearray()
        self._truncated = False

    def append(self, data: bytes) -> None:
        self._buf.extend(data)
        overflow = len(self._buf) - self._cap
        if overflow > 0:
            del self._buf[:overflow]
            self._truncated = True

    def snapshot(self) -> bytes:
        return bytes(self._buf)

    @property
    def truncated(self) -> bool:
        return self._truncated


class PtySession:
    def __init__(
        self,
        key: str,
        bridge,
        *,
        buffer_cap: int,
        read_timeout: float,
        identity: Optional[str] = None,
    ) -> None:
        self.key = key
        self.identity = identity
        self.bridge = bridge
        self.buffer = RingBuffer(buffer_cap)
        self.alive = True
        self.attached = False
        self.last_detached_at: Optional[float] = None
        self._read_timeout = read_timeout
        self._ws = None
        self._drain_task: Optional[asyncio.Task] = None
        self._state_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._terminal_close_code = WS_CLOSE_PROCESS_EXITED

    async def start(self) -> None:
        self._drain_task = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            chunk = await loop.run_in_executor(None, self.bridge.read, self._read_timeout)
            if chunk is None:                       # EOF — the agent process exited
                async with self._state_lock:
                    self.alive = False
                    self._terminal_close_code = WS_CLOSE_PROCESS_EXITED
                    ws = self._ws
                    self._ws = None
                    self.attached = False
                if ws is not None:
                    try:
                        await ws.close(code=WS_CLOSE_PROCESS_EXITED)
                    except Exception:
                        pass
                return
            if not chunk:                            # idle tick
                await asyncio.sleep(0)
                continue
            # Keep buffer publication and live forwarding ordered with attach's
            # snapshot replay.  Otherwise output arriving during replay can be
            # sent live first and then duplicated by the snapshot.
            async with self._state_lock:
                self.buffer.append(chunk)
                ws = self._ws
            if ws is not None:
                try:
                    await ws.send_bytes(chunk)
                except Exception:
                    pass                             # detached mid-send; keep buffering

    async def attach(self, ws) -> None:
        async with self._state_lock:
            if not self.alive:
                try:
                    # A process may exit after producing output but before the
                    # browser reconnects.  Preserve the keep-alive contract by
                    # replaying that final buffer before signalling why this
                    # socket cannot become the active attachment.
                    snap = self.buffer.snapshot()
                    if snap:
                        await ws.send_bytes(snap)
                    await ws.close(code=self._terminal_close_code)
                except Exception:
                    pass
                return

            old = self._ws
            published = False
            try:
                # Close the previous socket before publishing the replacement.
                # If this await is cancelled, the incoming socket never becomes
                # registry state.  The old handler may detach while close()
                # yields; publishing after it returns remains safe.
                if old is not None and old is not ws:
                    try:
                        await old.close(code=WS_CLOSE_SUPERSEDED)
                    except Exception:
                        pass
                self._ws = ws
                self.attached = True
                self.last_detached_at = None
                published = True
                snap = self.buffer.snapshot()
                if snap:
                    await ws.send_bytes(snap)
            except BaseException:
                # pty_ws has not entered its writer-loop try/finally yet, so an
                # interrupted snapshot must roll itself back to a reapable state.
                if published and self._ws is ws:
                    self._ws = None
                    self.attached = False
                    self.last_detached_at = time.monotonic()
                raise

    def detach(self, ws) -> None:
        # Only the currently-attached socket may mark the session detached.
        # A superseded socket's handler also calls detach on its way out
        # (its ``finally`` runs after the new tab attached); flipping
        # ``attached`` then would make a session with a live viewer look
        # idle and reapable.
        if self._ws is not ws:
            return
        self._ws = None
        self.attached = False
        self.last_detached_at = time.monotonic()

    async def close(self) -> None:
        async with self._state_lock:
            self.alive = False
            self._terminal_close_code = WS_CLOSE_PROCESS_EXITED
            self._ws = None
            self.attached = False
        await self._close_resources()

    async def _close_resources(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            drain_task = self._drain_task
            self._drain_task = None
            if drain_task is not None:
                drain_task.cancel()
                try:
                    await drain_task
                except (asyncio.CancelledError, Exception):
                    pass
            try:
                # bridge.close() joins the child — blocking; keep it off the
                # event loop (#53227).
                await asyncio.to_thread(self.bridge.close)
            except Exception:
                pass

    async def supersede(self) -> None:
        async with self._state_lock:
            self.alive = False
            self._terminal_close_code = WS_CLOSE_SUPERSEDED
            ws = self._ws
            self._ws = None
            self.attached = False
        if ws is not None:
            try:
                await ws.close(code=WS_CLOSE_SUPERSEDED)
            except Exception:
                pass
        await self._close_resources()


from typing import Callable, Dict, Tuple


class RegistryFull(Exception):
    pass


async def run_reaper(registry: "PtySessionRegistry", *, interval: float = 60.0) -> None:
    """Periodically reap idle/dead keep-alive sessions. Cancelled on shutdown."""
    while True:
        await asyncio.sleep(interval)
        try:
            await registry.reap_idle()
        except Exception:
            pass


class PtySessionRegistry:
    def __init__(self, *, ttl: float, max_sessions: int,
                 buffer_cap: int, read_timeout: float) -> None:
        self._ttl = ttl
        self._max = max_sessions
        self._buffer_cap = buffer_cap
        self._read_timeout = read_timeout
        self._sessions: Dict[str, PtySession] = {}
        self._lock = asyncio.Lock()

    async def attach_or_spawn(
        self,
        key: str,
        *,
        spawn: Callable[[], object],
        identity: Optional[str] = None,
        replace: bool = False,
    ) -> Tuple[PtySession, bool]:
        async with self._lock:
            await self._reap_idle_locked()
            existing = self._sessions.get(key)
            if (
                existing is not None
                and existing.alive
                and not replace
                and existing.identity == identity
            ):
                return existing, False
            if existing is not None:
                self._sessions.pop(key, None)
                if existing.alive:
                    await existing.supersede()
                else:
                    await existing.close()
            if len(self._sessions) >= self._max:
                self._reap_one_idle_or_raise()
            # PTY spawn does blocking fork/exec work — keep it off the event
            # loop (#53227). The registry lock intentionally spans the spawn:
            # otherwise two same-token requests can both miss and leak one PTY.
            cancel_requested = threading.Event()

            def _spawn_owned():
                bridge = spawn()
                if cancel_requested.is_set():
                    try:
                        bridge.close()
                    except Exception:
                        pass
                    return None
                return bridge

            spawn_task = asyncio.create_task(asyncio.to_thread(_spawn_owned))
            try:
                # Shield the blocking spawn thread from request cancellation so
                # it can retain ownership of any bridge it creates.
                bridge = await asyncio.shield(spawn_task)
            except asyncio.CancelledError:
                cancel_requested.set()
                loop = asyncio.get_running_loop()

                def _close_late_bridge(done: asyncio.Task) -> None:
                    if done.cancelled():
                        return
                    try:
                        late_bridge = done.result()
                    except BaseException:
                        return
                    if late_bridge is None:
                        return
                    try:
                        loop.run_in_executor(None, late_bridge.close)
                    except RuntimeError:
                        # Event-loop shutdown is the only expected rejection;
                        # close synchronously then so the child is not leaked.
                        try:
                            late_bridge.close()
                        except Exception:
                            pass

                # Cancellation must return immediately even though a worker
                # thread cannot be killed.  The worker closes the common case;
                # this callback covers the race where it returned just before
                # cancel_requested became visible.
                spawn_task.add_done_callback(_close_late_bridge)
                raise

            if bridge is None:  # defensive; only cancellation sets the flag
                raise RuntimeError("PTY spawn cancelled without request cancellation")

            try:
                session = PtySession(
                    key,
                    bridge,
                    buffer_cap=self._buffer_cap,
                    read_timeout=self._read_timeout,
                    identity=identity,
                )
                await session.start()
            except BaseException:
                try:
                    await asyncio.to_thread(bridge.close)
                except Exception:
                    pass
                raise
            self._sessions[key] = session
            return session, True

    def detach(self, key: str, ws) -> None:
        s = self._sessions.get(key)
        if s is not None:
            s.detach(ws)

    async def reap_idle(self, now: Optional[float] = None) -> None:
        async with self._lock:
            await self._reap_idle_locked(now)

    async def _reap_idle_locked(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        doomed = [
            key for key, s in self._sessions.items()
            if (not s.alive)
            or (not s.attached and s.last_detached_at is not None
                and (now - s.last_detached_at) > self._ttl)
        ]
        for key in doomed:
            await self._sessions.pop(key).close()

    def _reap_one_idle_or_raise(self) -> None:
        idle = [s for s in self._sessions.values()
                if not s.attached and s.last_detached_at is not None]
        if not idle:
            raise RegistryFull()
        oldest = min(idle, key=lambda s: s.last_detached_at or 0.0)
        self._sessions.pop(oldest.key, None)
        asyncio.create_task(oldest.close())

    async def close_all(self) -> None:
        async with self._lock:
            for key in list(self._sessions):
                await self._sessions.pop(key).close()
