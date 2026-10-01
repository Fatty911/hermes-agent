import asyncio
import threading
import time

import pytest

from hermes_cli.pty_session import RingBuffer


def test_ringbuffer_keeps_everything_under_capacity():
    rb = RingBuffer(10)
    rb.append(b"abc")
    rb.append(b"def")
    assert rb.snapshot() == b"abcdef"
    assert rb.truncated is False


def test_ringbuffer_drops_oldest_over_capacity():
    rb = RingBuffer(4)
    rb.append(b"abcdef")          # 6 bytes into a 4-byte buffer
    assert rb.snapshot() == b"cdef"
    assert rb.truncated is True


def test_ringbuffer_truncation_across_appends():
    rb = RingBuffer(3)
    rb.append(b"ab")
    rb.append(b"cd")             # now "abcd" -> keep "bcd"
    assert rb.snapshot() == b"bcd"
    assert rb.truncated is True


class FakeBridge:
    """Implements the bridge contract PtySession depends on."""

    def __init__(self, chunks):
        self._chunks = list(chunks)   # bytes; b"" = idle tick; None = EOF
        self.written = bytearray()
        self.closed = False
        self.resized = None

    def read(self, timeout):
        if not self._chunks:
            return b""                # idle
        return self._chunks.pop(0)

    def write(self, data):
        self.written.extend(data)

    def resize(self, cols, rows):
        self.resized = (cols, rows)

    def close(self):
        self.closed = True


class FakeWS:
    def __init__(self):
        self.sent = []               # list of ("bytes"|"text", payload)
        self.close_code = None

    async def send_bytes(self, data):
        self.sent.append(("bytes", bytes(data)))

    async def send_text(self, text):
        self.sent.append(("text", text))

    async def close(self, code=1000, reason=""):
        self.close_code = code


class BlockingCloseWS(FakeWS):
    def __init__(self, entered, release):
        super().__init__()
        self._entered = entered
        self._release = release

    async def close(self, code=1000, reason=""):
        self._entered.set()
        await asyncio.to_thread(self._release.wait, 1.0)
        await super().close(code=code, reason=reason)


class BlockingReplayWS(FakeWS):
    def __init__(self, entered, release):
        super().__init__()
        self._entered = entered
        self._release = release

    async def send_bytes(self, data):
        await super().send_bytes(data)
        if len(self.sent) == 1:
            self._entered.set()
            await self._release.wait()


class GatedBridge(FakeBridge):
    def __init__(self, chunk):
        super().__init__([])
        self._chunk = chunk
        self._released = threading.Event()

    def read(self, timeout):
        self._released.wait(1.0)
        if self._chunk is None:
            return b""
        chunk, self._chunk = self._chunk, None
        return chunk

    def release(self):
        self._released.set()

    def close(self):
        self.release()
        super().close()


@pytest.mark.asyncio
async def test_attach_replays_buffer_then_streams_live():
    from hermes_cli.pty_session import PtySession
    bridge = FakeBridge([b"hello ", b"world", None])
    s = PtySession("k", bridge, buffer_cap=1024, read_timeout=0.01)
    await s.start()
    await asyncio.sleep(0.05)                      # drain consumes "hello world"
    ws = FakeWS()
    await s.attach(ws)
    replay = b"".join(p for kind, p in ws.sent if kind == "bytes")
    assert replay == b"hello world"
    await s.close()


@pytest.mark.asyncio
async def test_detach_keeps_draining_into_buffer():
    from hermes_cli.pty_session import PtySession
    bridge = FakeBridge([b"one", b"", b"two"])
    s = PtySession("k", bridge, buffer_cap=1024, read_timeout=0.01)
    await s.start()
    ws = FakeWS()
    await s.attach(ws)
    s.detach(ws)
    assert s.attached is False
    assert s.last_detached_at is not None
    await asyncio.sleep(0.05)                      # "two" drains while detached
    ws2 = FakeWS()
    await s.attach(ws2)
    replay = b"".join(p for kind, p in ws2.sent if kind == "bytes")
    assert replay == b"onetwo"
    await s.close()


@pytest.mark.asyncio
async def test_eof_marks_dead_and_closes_socket_4410():
    from hermes_cli.pty_session import PtySession
    bridge = FakeBridge([b"bye", None])
    s = PtySession("k", bridge, buffer_cap=1024, read_timeout=0.01)
    await s.start()
    ws = FakeWS()
    await s.attach(ws)
    await asyncio.sleep(0.05)                      # drain hits None (EOF)
    assert s.alive is False
    assert ws.close_code == 4410
    await s.close()


from hermes_cli.pty_session import PtySessionRegistry, RegistryFull


def make_registry(ttl=1800.0, max_sessions=16):
    return PtySessionRegistry(ttl=ttl, max_sessions=max_sessions,
                              buffer_cap=1024, read_timeout=0.01)


@pytest.mark.asyncio
async def test_same_key_reattaches_same_session():
    reg = make_registry()
    b1 = FakeBridge([b"", b"", b""])
    s1, created1 = await reg.attach_or_spawn("tok", spawn=lambda: b1)
    s2, created2 = await reg.attach_or_spawn("tok", spawn=lambda: FakeBridge([]))
    assert created1 is True and created2 is False
    assert s1 is s2
    assert s2.bridge is b1                     # second spawn callable was NOT used
    await reg.close_all()


@pytest.mark.asyncio
async def test_same_key_replaces_session_when_identity_changes():
    reg = make_registry()
    b1 = FakeBridge([b"", b"", b""])
    s1, _ = await reg.attach_or_spawn(
        "tok", identity="fresh", spawn=lambda: b1
    )
    b2 = FakeBridge([b"", b"", b""])
    s2, created = await reg.attach_or_spawn(
        "tok", identity="resume:session-a", spawn=lambda: b2
    )

    assert created is True
    assert s2 is not s1
    assert b1.closed is True
    assert s2.bridge is b2
    await reg.close_all()


@pytest.mark.asyncio
async def test_concurrent_same_identity_spawns_once():
    reg = make_registry()
    spawn_started = threading.Event()
    release_spawn = threading.Event()
    spawned = []

    def spawn():
        bridge = FakeBridge([b"", b""])
        spawned.append(bridge)
        spawn_started.set()
        release_spawn.wait(1.0)
        return bridge

    first = asyncio.create_task(
        reg.attach_or_spawn("tok", identity="fresh", spawn=spawn)
    )
    assert await asyncio.to_thread(spawn_started.wait, 1.0)
    second = asyncio.create_task(
        reg.attach_or_spawn("tok", identity="fresh", spawn=spawn)
    )
    await asyncio.sleep(0.01)
    release_spawn.set()

    (s1, created1), (s2, created2) = await asyncio.gather(first, second)
    assert len(spawned) == 1
    assert s1 is s2
    assert sorted((created1, created2)) == [False, True]
    await reg.close_all()


@pytest.mark.asyncio
async def test_cancelled_spawn_closes_unregistered_bridge():
    reg = make_registry()
    spawn_started = threading.Event()
    release_spawn = threading.Event()
    spawned = []

    def spawn():
        spawn_started.set()
        release_spawn.wait(1.0)
        bridge = FakeBridge([b""])
        spawned.append(bridge)
        return bridge

    pending = asyncio.create_task(
        reg.attach_or_spawn("tok", identity="fresh", spawn=spawn)
    )
    assert await asyncio.to_thread(spawn_started.wait, 1.0)
    pending.cancel()
    pending.cancel()  # repeated disconnect/shutdown cancellation is also safe

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 0.2)
    assert spawned == []
    assert reg._sessions == {}

    release_spawn.set()
    deadline = asyncio.get_running_loop().time() + 1.0
    while (not spawned or not spawned[0].closed) and (
        asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)
    assert len(spawned) == 1
    assert spawned[0].closed is True
    assert reg._sessions == {}


@pytest.mark.asyncio
async def test_concurrent_identity_change_spawns_one_replacement():
    reg = make_registry()
    original = FakeBridge([b"", b""])
    await reg.attach_or_spawn("tok", identity="fresh", spawn=lambda: original)

    spawn_started = threading.Event()
    release_spawn = threading.Event()
    replacements = []

    def spawn_replacement():
        bridge = FakeBridge([b"", b""])
        replacements.append(bridge)
        spawn_started.set()
        release_spawn.wait(1.0)
        return bridge

    first = asyncio.create_task(
        reg.attach_or_spawn(
            "tok", identity="resume:session-a", spawn=spawn_replacement
        )
    )
    assert await asyncio.to_thread(spawn_started.wait, 1.0)
    second = asyncio.create_task(
        reg.attach_or_spawn(
            "tok", identity="resume:session-a", spawn=spawn_replacement
        )
    )
    await asyncio.sleep(0.01)
    release_spawn.set()

    (s1, created1), (s2, created2) = await asyncio.gather(first, second)
    assert original.closed is True
    assert len(replacements) == 1
    assert s1 is s2
    assert sorted((created1, created2)) == [False, True]
    await reg.close_all()


@pytest.mark.asyncio
async def test_replace_forces_new_session_with_same_identity():
    reg = make_registry()
    b1 = FakeBridge([b"", b"", b""])
    await reg.attach_or_spawn("tok", identity="fresh", spawn=lambda: b1)
    b2 = FakeBridge([b"", b"", b""])
    _session, created = await reg.attach_or_spawn(
        "tok", identity="fresh", replace=True, spawn=lambda: b2
    )

    assert created is True
    assert b1.closed is True
    await reg.close_all()


@pytest.mark.asyncio
async def test_concurrent_attaches_supersede_intermediate_socket():
    from hermes_cli.pty_session import PtySession

    bridge = FakeBridge([b"", b""])
    session = PtySession("tok", bridge, buffer_cap=1024, read_timeout=0.01)
    await session.start()

    close_entered = threading.Event()
    release_close = threading.Event()
    original = BlockingCloseWS(close_entered, release_close)
    await session.attach(original)

    first_replacement = FakeWS()
    second_replacement = FakeWS()
    first = asyncio.create_task(session.attach(first_replacement))
    assert await asyncio.to_thread(close_entered.wait, 1.0)
    second = asyncio.create_task(session.attach(second_replacement))
    await asyncio.sleep(0.01)
    release_close.set()
    await asyncio.gather(first, second)

    assert original.close_code == 4409
    assert first_replacement.close_code == 4409
    assert second_replacement.close_code is None
    assert session._ws is second_replacement
    await session.close()


@pytest.mark.asyncio
async def test_snapshot_replay_precedes_live_output_without_duplication():
    from hermes_cli.pty_session import PtySession

    bridge = GatedBridge(b"live")
    session = PtySession("tok", bridge, buffer_cap=1024, read_timeout=0.01)
    session.buffer.append(b"history")
    await session.start()

    replay_entered = asyncio.Event()
    release_replay = asyncio.Event()
    ws = BlockingReplayWS(replay_entered, release_replay)
    attaching = asyncio.create_task(session.attach(ws))
    await asyncio.wait_for(replay_entered.wait(), 1.0)

    bridge.release()
    await asyncio.sleep(0.05)
    assert [payload for kind, payload in ws.sent if kind == "bytes"] == [b"history"]

    release_replay.set()
    await attaching
    deadline = asyncio.get_running_loop().time() + 1.0
    while len(ws.sent) < 2 and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert [payload for kind, payload in ws.sent if kind == "bytes"] == [
        b"history",
        b"live",
    ]
    await session.close()


@pytest.mark.asyncio
async def test_cancelled_snapshot_attach_rolls_back_to_detached():
    from hermes_cli.pty_session import PtySession

    session = PtySession(
        "tok", FakeBridge([b""]), buffer_cap=1024, read_timeout=0.01
    )
    session.buffer.append(b"history")
    await session.start()

    replay_entered = asyncio.Event()
    never_release = asyncio.Event()
    ws = BlockingReplayWS(replay_entered, never_release)
    attaching = asyncio.create_task(session.attach(ws))
    await asyncio.wait_for(replay_entered.wait(), 1.0)
    attaching.cancel()

    with pytest.raises(asyncio.CancelledError):
        await attaching
    assert session._ws is None
    assert session.attached is False
    assert session.last_detached_at is not None
    await session.close()


@pytest.mark.asyncio
async def test_cancelled_old_socket_close_does_not_publish_replacement():
    from hermes_cli.pty_session import PtySession

    session = PtySession(
        "tok", FakeBridge([b""]), buffer_cap=1024, read_timeout=0.01
    )
    await session.start()
    close_entered = threading.Event()
    release_close = threading.Event()
    old = BlockingCloseWS(close_entered, release_close)
    await session.attach(old)

    replacement = FakeWS()
    attaching = asyncio.create_task(session.attach(replacement))
    assert await asyncio.to_thread(close_entered.wait, 1.0)
    attaching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attaching

    assert session._ws is old
    assert session.attached is True
    assert replacement.close_code is None
    release_close.set()
    await session.close()


@pytest.mark.asyncio
async def test_attach_after_supersede_is_rejected():
    from hermes_cli.pty_session import PtySession

    session = PtySession(
        "tok", FakeBridge([b"", b""]), buffer_cap=1024, read_timeout=0.01
    )
    await session.start()
    await session.supersede()

    late = FakeWS()
    await session.attach(late)

    assert late.close_code == 4409
    assert session.attached is False


@pytest.mark.asyncio
async def test_reap_idle_closes_sessions_past_ttl():
    reg = make_registry(ttl=10.0)
    b = FakeBridge([b"", b""])
    s, _ = await reg.attach_or_spawn("tok", spawn=lambda: b)
    ws = FakeWS()
    await s.attach(ws)
    s.detach(ws)
    s.last_detached_at = time.monotonic() - 11.0   # detached 11s ago, ttl 10s
    await reg.reap_idle()
    assert b.closed is True
    s2, created = await reg.attach_or_spawn("tok", spawn=lambda: FakeBridge([]))
    assert created is True
    await reg.close_all()


@pytest.mark.asyncio
async def test_new_key_at_capacity_raises_when_none_reapable():
    reg = make_registry(max_sessions=1)
    b = FakeBridge([b"", b""])
    s, _ = await reg.attach_or_spawn("a", spawn=lambda: b)
    await s.attach(FakeWS())                    # attached → not reapable
    with pytest.raises(RegistryFull):
        await reg.attach_or_spawn("b", spawn=lambda: FakeBridge([]))
    await reg.close_all()


@pytest.mark.asyncio
async def test_reaper_loop_invokes_reap(monkeypatch):
    from hermes_cli.pty_session import run_reaper
    reg = make_registry()
    calls = {"n": 0}

    async def fake_reap(now=None):
        calls["n"] += 1

    monkeypatch.setattr(reg, "reap_idle", fake_reap)
    task = asyncio.create_task(run_reaper(reg, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2
