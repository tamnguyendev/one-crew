"""The existing v1 stable-file controller lock, shared without workflow engines."""
from contextlib import contextmanager
import time
from .ledger import LedgerError, key_field

@contextmanager
def task_lock(ledger, task_id, wait=0.0):
    # Stable file: never unlink a lock while another process could have it open.
    import msvcrt
    path = ledger.state_root / 'locks' / (key_field(task_id) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        # wait: a real owner holds the lock for its whole life; a host probing whether it is held (host._runner_lock_held)
        # holds it for microseconds, so the runner waits briefly instead of losing the task to the probe. Callers with
        # their own retry loop keep failing fast (wait=0).
        deadline = time.monotonic() + wait
        while True:
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if time.monotonic() >= deadline: raise LedgerError('A controller already owns this task.') from error
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
