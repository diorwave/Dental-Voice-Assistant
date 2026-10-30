"""Minimal, safe-ish background execution for work that must not block a
voice turn (e.g. Twilio can take several seconds and Vapi will time out).

Compared with the raw ``threading.Thread`` calls this replaces:

* a bounded pool, so a burst of calls can't spawn unbounded threads;
* each task gets fresh DB connections and closes them afterwards, so worker
  threads don't leak connections;
* exceptions are logged instead of silently killing the thread;
* ``ThreadPoolExecutor`` joins its threads at interpreter shutdown, so a
  graceful gunicorn worker recycle finishes queued work instead of dropping it.

Callers should persist a status (e.g. ``Appointment.sms_status = "pending"``)
before submitting, so work lost to a hard kill is visible and retryable. A
real task queue with retries is tracked in #20.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

_executor = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.BACKGROUND_TASK_WORKERS, thread_name_prefix="bg-task"
        )
    return _executor


def run_in_background(fn, *args, **kwargs) -> None:
    name = getattr(fn, "__name__", repr(fn))

    if settings.BACKGROUND_TASKS_EAGER:
        # Tests / debugging: run inline on the caller's connection.
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("[BACKGROUND] task %s failed", name)
        return

    def _runner():
        close_old_connections()
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("[BACKGROUND] task %s failed", name)
        finally:
            close_old_connections()

    _get_executor().submit(_runner)
