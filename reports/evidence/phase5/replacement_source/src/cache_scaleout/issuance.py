"""Mark actual client issuance after connection acquisition, before driver IO."""
from contextlib import contextmanager
from contextvars import ContextVar

_on_issue = ContextVar('paper2_on_issue', default=None)
_priority = ContextVar('paper2_observation_priority', default=False)


@contextmanager
def issuing(callback, *, priority=False):
    token = _on_issue.set(callback)
    priority_token = _priority.set(priority)
    try:
        yield
    finally:
        _on_issue.reset(token)
        _priority.reset(priority_token)


def observation_priority():
    return _priority.get()


def notify_issued():
    callback = _on_issue.get()
    if callback is not None:
        callback()
