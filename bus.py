# bus.py
from __future__ import annotations
import os, json, time, threading, queue, typing as t

try:
    import redis  # pip install redis
except Exception:  # redis optional (fallback to in-memory)
    redis = None


KEEPALIVE_SEC = int(os.getenv("SSE_KEEPALIVE_SEC", "15"))


class BaseBus:
    """Abstract interface."""

    def publish(self, job_id: str, event: dict) -> None:
        raise NotImplementedError

    def request_cancel(self, job_id: str) -> None:
        raise NotImplementedError

    def is_cancelled(self, job_id: str) -> bool:
        raise NotImplementedError

    def sse(self, job_id: str):
        """Return an iterator yielding Server-Sent Events bytes."""
        raise NotImplementedError


# ---------------- In-memory (single-worker) ----------------
class InMemoryBus(BaseBus):
    def __init__(self):
        self._qs: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()
        self._cancels: set[str] = set()

    def _subscribe_queue(self, job_id: str) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._qs.setdefault(job_id, []).append(q)
        return q

    def publish(self, job_id: str, event: dict) -> None:
        with self._lock:
            for q in self._qs.get(job_id, []):
                q.put(event)

    def request_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancels.add(job_id)
        # also emit a line so UIs can log it immediately
        self.publish(job_id, {"message": "Cancel requested"})

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancels

    def sse(self, job_id: str):
        q = self._subscribe_queue(job_id)
        last = time.time()
        # prime a welcome
        yield b": ok\n\n"
        while True:
            try:
                evt = q.get(timeout=1.0)
                data = json.dumps(evt, separators=(",", ":")).encode("utf-8")
                yield b"data: " + data + b"\n\n"
                last = time.time()
            except queue.Empty:
                now = time.time()
                if now - last >= KEEPALIVE_SEC:
                    yield b": keepalive\n\n"
                    last = now


# ---------------- Redis-backed (multi-worker) ----------------
class RedisBus(BaseBus):
    def __init__(self, url: str):
        # decode_responses=False → we send/receive bytes; safer
        self.r = redis.from_url(url, decode_responses=False)
        self.cancel_ttl = int(os.getenv("REDIS_CANCEL_TTL", "86400"))  # 1 day

    def _chan(self, job_id: str) -> bytes:
        return f"jobs:{job_id}:events".encode("utf-8")

    def _cancel_key(self, job_id: str) -> bytes:
        return f"jobs:{job_id}:cancel".encode("utf-8")

    def publish(self, job_id: str, event: dict) -> None:
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        self.r.publish(self._chan(job_id), payload)

    def request_cancel(self, job_id: str) -> None:
        k = self._cancel_key(job_id)
        self.r.set(k, b"1", ex=self.cancel_ttl)
        # also publish a human line
        self.publish(job_id, {"message": "Cancel requested"})

    def is_cancelled(self, job_id: str) -> bool:
        k = self._cancel_key(job_id)
        return self.r.get(k) is not None

    def sse(self, job_id: str):
        pubsub = self.r.pubsub(ignore_subscribe_messages=True)
        chan = self._chan(job_id)
        pubsub.subscribe(chan)

        last = time.time()
        try:
            yield b": ok\n\n"
            while True:
                msg = pubsub.get_message(timeout=1.5)
                if msg and msg.get("type") == "message":
                    payload = msg.get("data", b"")
                    if payload:
                        yield b"data: " + payload + b"\n\n"
                        last = time.time()
                # keepalive
                now = time.time()
                if now - last >= KEEPALIVE_SEC:
                    yield b": keepalive\n\n"
                    last = now
        finally:
            try:
                pubsub.unsubscribe(chan)
                pubsub.close()
            except Exception:
                pass


def _make_bus() -> BaseBus:
    url = os.getenv("REDIS_URL") or ""
    if url and redis is not None:
        return RedisBus(url)
    return InMemoryBus()


# Singleton used everywhere
bus: BaseBus = _make_bus()
