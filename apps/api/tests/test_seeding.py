"""Tests for app.services.ml.seeding — reproducibility helpers.

Core property under test: calling seed_everything(1750) before building and
briefly training a tiny model yields BIT-IDENTICAL weights and metrics across
two independent runs. Tiny data (<=10 rows), 2 epochs, CPU only.
"""

from __future__ import annotations

import os

# TF CPU only — must precede any TF/Keras import.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.services.ml.seeding import derive_seed, seed_everything  # noqa: E402

SEED = 1750


# ---------------------------------------------------------------------------
# derive_seed
# ---------------------------------------------------------------------------

class TestDeriveSeed:
    def test_in_uint32_range(self):
        s = derive_seed(SEED, "model_A")
        assert 0 <= s <= 0xFFFFFFFF

    def test_deterministic_for_same_inputs(self):
        # Within a single process, hash() is stable for the same args.
        assert derive_seed(SEED, "x") == derive_seed(SEED, "x")

    def test_different_labels_usually_differ(self):
        assert derive_seed(SEED, "model_A") != derive_seed(SEED, "model_B")


# ---------------------------------------------------------------------------
# seed_everything — RNG reproducibility (cheap, no TF graph)
# ---------------------------------------------------------------------------

class TestSeedEverythingRng:
    def test_numpy_reproducible(self):
        seed_everything(SEED, enable_op_determinism=False)
        a = np.random.rand(5)
        seed_everything(SEED, enable_op_determinism=False)
        b = np.random.rand(5)
        np.testing.assert_array_equal(a, b)

    def test_python_random_reproducible(self):
        import random

        seed_everything(SEED, enable_op_determinism=False)
        a = [random.random() for _ in range(5)]
        seed_everything(SEED, enable_op_determinism=False)
        b = [random.random() for _ in range(5)]
        assert a == b

    def test_sets_pythonhashseed(self):
        seed_everything(SEED, enable_op_determinism=False)
        assert os.environ["PYTHONHASHSEED"] == str(SEED)


# ---------------------------------------------------------------------------
# seed_everything — end-to-end training reproducibility
# ---------------------------------------------------------------------------

def _tiny_train_run(seed: int):
    """Seed, build a tiny model, train 2 epochs on fixed data, return state."""
    import tensorflow as tf
    from tensorflow import keras

    seed_everything(seed)

    # Fixed synthetic data (NOT drawn from a seeded RNG so the only source of
    # run-to-run variance is the network init / shuffling controlled by the seed).
    x = np.linspace(-1.0, 1.0, 10, dtype=np.float32).reshape(10, 1)
    y = (2.0 * x + 0.3).astype(np.float32)

    model = keras.Sequential(
        [
            keras.layers.Input(shape=(1,)),
            keras.layers.Dense(4, activation="relu", kernel_initializer="he_normal"),
            keras.layers.Dense(1, activation="linear"),
        ]
    )
    model.compile(optimizer=keras.optimizers.Adam(0.01), loss="mse")
    history = model.fit(x, y, epochs=2, batch_size=4, shuffle=True, verbose=0)

    weights = [w.copy() for w in model.get_weights()]
    final_loss = float(history.history["loss"][-1])
    return weights, final_loss


class TestTrainingReproducibility:
    def test_identical_weights_and_loss_across_runs(self):
        w1, loss1 = _tiny_train_run(SEED)
        w2, loss2 = _tiny_train_run(SEED)

        # Shapes are sanity-checked, then bit-exactness asserted.
        assert len(w1) == len(w2) and len(w1) > 0
        for a, b in zip(w1, w2):
            assert a.shape == b.shape
            np.testing.assert_array_equal(a, b)

        assert loss1 == loss2

    def test_different_seed_changes_init(self):
        w1, _ = _tiny_train_run(SEED)
        w2, _ = _tiny_train_run(SEED + 1)
        # At least one weight tensor must differ with a different seed.
        any_diff = any(not np.array_equal(a, b) for a, b in zip(w1, w2))
        assert any_diff
