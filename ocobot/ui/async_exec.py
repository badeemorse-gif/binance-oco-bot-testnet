"""Async execution layer — keep ALL IO off the Qt UI thread (T10c).

``AsyncRunner`` runs a callable in a ``QThreadPool`` worker thread and delivers
its outcome back to the UI thread via Qt signals (queued delivery), so the UI
never freezes. It performs NO network itself — callers submit service-layer
callables (e.g. a preflight function) that already own any IO.

Signals live on ``WorkerSignals(QObject)`` created on the UI thread so their
emissions are delivered as queued cross-thread events to the UI thread.
"""

from ._qt import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    """Signals emitted by a worker. Create on the UI thread for queued delivery.

    - ``started``: emitted just before the callable runs.
    - ``result``: emitted with the return value on success.
    - ``failed``: emitted with the raised exception on error.
    - ``finished``: emitted at the very end (success or failure).
    """

    started = Signal()
    finished = Signal()
    result = Signal(object)
    failed = Signal(object)


class _Worker(QRunnable):
    """A ``QRunnable`` that invokes ``fn(*args, **kwargs)`` in a pool thread."""

    def __init__(self, signals, fn, args, kwargs):
        super().__init__()
        self._signals = signals
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        # Do NOT let the pool auto-delete this QRunnable the instant run()
        # returns: a fast/failing callable finishes before the UI thread has
        # processed the queued signal events, and destroying the C++ object
        # (which owns/references the signal emitter) mid-delivery drops the
        # queued QMetaCallEvent — the receiving QEventLoop then never gets its
        # quit() and blocks forever. AsyncRunner keeps a strong ref instead.
        self.setAutoDelete(False)

    def run(self):  # pragma: no cover - executed on a pool thread
        self._signals.started.emit()
        try:
            value = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - surface any error via signal
            self._signals.failed.emit(exc)
        else:
            self._signals.result.emit(value)
        finally:
            self._signals.finished.emit()


class AsyncRunner:
    """Submit callables to a thread pool; deliver outcomes via Qt signals.

    Construct on the UI thread. ``submit`` returns immediately (non-blocking)
    and the callable runs on a pool thread.
    """

    def __init__(self, pool=None):
        self._pool = pool or QThreadPool.globalInstance()
        # Strong refs to in-flight workers so neither Python GC nor the pool's
        # auto-delete can destroy a worker (and its signal emitter) while its
        # queued outcome event is still waiting to be processed on the UI
        # thread. Cleared per-worker once its ``finished`` signal is delivered.
        self._inflight = set()

    def submit(self, fn, *args, on_result=None, on_error=None, **kwargs):
        """Run ``fn(*args, **kwargs)`` on a pool thread; return immediately.

        Optional ``on_result(value)`` / ``on_error(exc)`` callbacks are
        connected to the worker's signals (queued delivery to the UI thread).
        Returns the ``WorkerSignals`` object so callers can connect more slots.
        """
        signals = WorkerSignals()
        if on_result is not None:
            signals.result.connect(on_result)
        if on_error is not None:
            signals.failed.connect(on_error)

        worker = _Worker(signals, fn, args, kwargs)
        # Keep the worker alive until its outcome has been delivered to the UI
        # thread; release it on ``finished`` (queued, so it runs only after all
        # earlier queued result/failed slots for this worker have executed).
        self._inflight.add(worker)
        signals.finished.connect(lambda: self._inflight.discard(worker))
        self._pool.start(worker)
        return signals
