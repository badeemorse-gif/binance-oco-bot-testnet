"""Non-blocking alert Notifier: bounded queue + single daemon worker.

Standard-library only. Qt-free and offline-testable.

Purpose
-------
Decouple audit-event-driven alerts from any hot path. The ``Notifier`` holds a
bounded queue and a single daemon worker thread. ``enqueue()`` is non-blocking
and never raises; the worker drains the queue and sends via the current
``TelegramClient`` to all current recipients with a short timeout + limited
retry, swallowing ALL exceptions so nothing can crash or slow the producer.

Logging never includes the bot token or full message bodies (length only).
No thread is started at import or construction time.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

logger = logging.getLogger("ocobot.alerts.notifier")


class Notifier:
    """Queue + worker that forwards alert text to Telegram off the hot path.

    Parameters (all keyword-only)
    -----------------------------
    client_provider:
        ``() -> Optional[TelegramClient]`` — None when not configured.
    recipients_provider:
        ``() -> list[str|int]`` of chat_ids.
    enabled_provider:
        ``() -> bool`` — defaults to always-enabled.
    max_queue:
        Bounded queue size (drop-on-full).
    retries:
        Number of *extra* attempts per recipient after the first.
    retry_delay:
        Seconds to sleep between attempts.
    logger:
        Optional logger override.
    """

    def __init__(self, *, client_provider, recipients_provider,
                 enabled_provider=None, max_queue=1000, retries=2,
                 retry_delay=0.5, logger=None):
        self._client_provider = client_provider
        self._recipients_provider = recipients_provider
        self._enabled_provider = enabled_provider if enabled_provider is not None else (lambda: True)
        self._retries = retries
        self._retry_delay = retry_delay
        self._log = logger if logger is not None else globals()["logger"]

        self._queue = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

        self._sent = 0
        self._failed = 0
        self._dropped = 0

    # -- lifecycle --------------------------------------------------------
    def start(self):
        """Start the daemon worker thread (no-op if already running)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="ocobot-notifier")
            self._thread.start()

    def stop(self, *, timeout=2.0):
        """Signal stop, unblock the worker with a sentinel, and join."""
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._thread = None

    # -- producer side ----------------------------------------------------
    def enqueue(self, text, *, parse_mode="MarkdownV2"):
        """Non-blocking enqueue. Returns True on success, False otherwise.

        Never raises. Drops (and counts) when disabled or the queue is full.
        Logging records the text *length* only — never the content or token.
        """
        try:
            if self._enabled_provider() is False:
                return False
            item = {"text": text, "parse_mode": parse_mode}
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self._dropped += 1
                self._log.warning(
                    "notifier queue full; dropping alert (text_len=%s)",
                    len(text) if text is not None else 0)
                return False
            return True
        except Exception:
            # enqueue must NEVER raise
            try:
                self._log.warning("notifier enqueue failed; alert dropped")
            except Exception:
                pass
            return False

    # -- worker side ------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                # sentinel -> stop
                break
            try:
                client = self._client_provider()
                if client is None:
                    self._failed += 1
                    continue
                recipients = list(self._recipients_provider() or [])
                for chat_id in recipients:
                    self._send_one(client, chat_id, item)
            except Exception:
                # swallow ALL exceptions — never crash the worker
                try:
                    self._log.warning("notifier worker swallowed an exception")
                except Exception:
                    pass
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _send_one(self, client, chat_id, item):
        """Send to one recipient with limited retry. Swallows all exceptions."""
        attempts = 0
        while attempts <= self._retries:
            try:
                client.send_message(
                    chat_id, item["text"], parse_mode=item["parse_mode"])
                self._sent += 1
                return
            except Exception:
                attempts += 1
                if attempts > self._retries:
                    self._failed += 1
                    # chat_id is OK to log; token/text are NOT.
                    self._log.warning(
                        "notifier send failed after %s attempt(s) (chat_id=%s)",
                        attempts, chat_id)
                else:
                    time.sleep(self._retry_delay)

    # -- introspection ----------------------------------------------------
    def stats(self):
        """Return current counters and running state."""
        return {
            "sent": self._sent,
            "failed": self._failed,
            "dropped": self._dropped,
            "queued": self._queue.qsize(),
            "running": bool(self._thread and self._thread.is_alive()),
        }
