"""Deliver background work to the UI thread without calling Tk from workers.

Input: callbacks with immutable snapshots/results. Output: main-thread callbacks.
Closing discards pending display work, never model data. Updated 2026-09-06.
"""
from queue import Empty, Queue
from threading import Lock


class UiDispatcher:
    def __init__(self):
        self._queue = Queue()
        self._lock = Lock()
        self._closed = False

    def post(self, callback, *args):
        with self._lock:
            if self._closed:
                return False
            self._queue.put((callback, args))
            return True

    def drain(self, limit=50):
        count = 0
        while not self._closed and count < limit:
            try:
                callback, args = self._queue.get_nowait()
            except Empty:
                break
            callback(*args)
            count += 1
        return count

    def close(self):
        with self._lock:
            self._closed = True
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    return
