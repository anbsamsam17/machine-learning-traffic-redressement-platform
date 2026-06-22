"""Per-user training concurrency + deadline guardrails (A9).

Bounds the cost a single user can impose on the API:

- `acquire_training_slot(user_id)` returns a context manager that holds a
  per-user `threading.Lock`. Concurrent starts from the same user raise
  HTTPException(409). Different users still run sequentially because a
  single `ThreadPoolExecutor(max_workers=1)` is created in the router and
  shared via this module (E2 will plumb the executor here when it
  refactors training.py).
- `enforce_grid_cap(n_combinations)` raises HTTPException(400) when the
  cartesian product exceeds `settings.MAX_GRID_COMBINATIONS` (default 100).
- `make_deadline()` returns the absolute `datetime` at which the grid
  search must stop; `TrainingDeadline.should_stop()` is called from the
  Keras `on_epoch_end` callback and sets `model.stop_training = True`
  when exceeded.

The router layer (E2) plugs this in. The helpers live in `app/` so they
can be unit-tested without importing TensorFlow.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from .config import get_settings

# ---------------------------------------------------------------------------
# Per-user concurrency lock
# ---------------------------------------------------------------------------

_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _get_user_lock(user_id: str) -> threading.Lock:
    """Return the singleton lock for *user_id* (created on demand)."""
    with _user_locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_locks[user_id] = lock
        return lock


@contextmanager
def acquire_training_slot(user_id: str) -> Iterator[None]:
    """Non-blocking acquisition of the per-user training lock.

    Raises HTTPException(409) immediately if the same user already has a
    training run in flight. Released when the context exits, so callers can
    safely use it across the lifetime of a Thread / Future.
    """
    lock = _get_user_lock(user_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un entrainement est deja en cours pour ce compte.",
        )
    try:
        yield
    finally:
        try:
            lock.release()
        except RuntimeError:
            # Already released (e.g. test teardown) — silent.
            pass


def release_training_slot(user_id: str) -> None:
    """Force-release the lock if the worker thread acquired it itself."""
    lock = _user_locks.get(user_id)
    if lock is None:
        return
    try:
        lock.release()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Grid-size cap
# ---------------------------------------------------------------------------


def enforce_grid_cap(n_combinations: int) -> None:
    """Refuse grids larger than `settings.MAX_GRID_COMBINATIONS`.

    The cartesian product
    `feature_subsets × activations × learning_rates × min_nb_epochs × losses
    × dropouts × neurons_factors × batch_sizes` easily reaches the thousands;
    capping it preserves the API for other tenants on a 2-core ARM A1.
    """
    cap = get_settings().MAX_GRID_COMBINATIONS
    if n_combinations > cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Grille de {n_combinations} combinaisons depasse la limite "
                f"({cap}). Reduisez les axes ou desactivez feature_subset_grid."
            ),
        )


# ---------------------------------------------------------------------------
# Wall-clock deadline
# ---------------------------------------------------------------------------


@dataclass
class TrainingDeadline:
    """Absolute deadline for a single training run.

    Initialised at the start of the grid search and consulted from the
    `on_epoch_end` Keras callback so the run aborts cleanly when
    `MAX_TRAINING_MINUTES` is exceeded.
    """

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    max_minutes: int = field(default_factory=lambda: get_settings().MAX_TRAINING_MINUTES)

    @property
    def deadline(self) -> datetime:
        return self.started_at + timedelta(minutes=self.max_minutes)

    def should_stop(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return current >= self.deadline


def make_deadline() -> TrainingDeadline:
    """Factory used by the router so tests can monkey-patch the timing."""
    return TrainingDeadline()
