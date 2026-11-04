"""Optional workbench progress events; no changes to normal CLI output."""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

PREFIX = "CLIP_REVIEW_PROGRESS "


class ReviewProgress:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.current: dict[str, str | float | None] | None = None
        self.clock = 0.0
        self.block = ""

    def emit(self) -> None:
        print(PREFIX + json.dumps(self.current, ensure_ascii=True), flush=True)

    def finish(self, state: str = "completed") -> None:
        if self.current is not None:
            self.current["state"] = state
            self.current["duration_seconds"] = max(0, time.monotonic() - self.clock)
            self.emit()
            self.current = None

    def start(self, label: str, block: str | None = None) -> None:
        self.finish()
        if block is not None:
            self.block = block
        if self.block:
            label += f" — bloco {self.block}"
        if self.prefix:
            label = f"{self.prefix} · {label}"
        self.clock = time.monotonic()
        self.current = {
            "id": uuid4().hex,
            "label": label,
            "state": "running",
            "started_at": time.time(),
            "duration_seconds": None,
        }
        self.emit()


_ACTIVE: ContextVar[ReviewProgress | None] = ContextVar("review_progress", default=None)


def phase(label: str, *, block: str | None = None) -> None:
    progress = _ACTIVE.get()
    if progress is not None:
        progress.start(label, block)


@contextmanager
def progress_session(prefix: str = "") -> Iterator[None]:
    progress = (
        ReviewProgress(prefix)
        if os.environ.get("CLIP_REVIEW_PROGRESS") == "1"
        else None
    )
    token = _ACTIVE.set(progress)
    try:
        yield
    except BaseException:
        if progress is not None:
            progress.finish("failed")
        raise
    else:
        if progress is not None:
            progress.finish()
    finally:
        _ACTIVE.reset(token)
