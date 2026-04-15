"""Tests for SessionManager (create, store, get, cleanup)."""

from __future__ import annotations

import time

import pytest

from app.session import Session, SessionManager


class TestSession:
    def test_session_creation(self):
        s = Session(session_id="abc", mode="TV")
        assert s.session_id == "abc"
        assert s.mode == "TV"
        assert isinstance(s.created_at, float)
        assert isinstance(s.data, dict)

    def test_session_touch(self):
        s = Session(session_id="abc", mode="TV")
        old_time = s.last_accessed
        time.sleep(0.01)
        s.touch()
        assert s.last_accessed > old_time

    def test_session_is_expired(self):
        s = Session(session_id="abc", mode="TV")
        assert not s.is_expired(ttl=3600)
        s.last_accessed = time.time() - 7300
        assert s.is_expired(ttl=7200)

    def test_session_data_default_empty(self):
        s = Session(session_id="abc", mode="TV")
        assert s.data == {}


class TestSessionManager:
    def test_create_session(self):
        mgr = SessionManager()
        session = mgr.create_session(mode="TV")
        assert session.session_id is not None
        assert len(session.session_id) == 32  # uuid4 hex
        assert session.mode == "TV"

    def test_create_session_pl(self):
        mgr = SessionManager()
        session = mgr.create_session(mode="PL")
        assert session.mode == "PL"

    def test_get_session_existing(self):
        mgr = SessionManager()
        s = mgr.create_session()
        retrieved = mgr.get_session(s.session_id)
        assert retrieved is not None
        assert retrieved.session_id == s.session_id

    def test_get_session_missing(self):
        mgr = SessionManager()
        assert mgr.get_session("nonexistent") is None

    def test_get_session_expired(self):
        mgr = SessionManager()
        s = mgr.create_session()
        s.last_accessed = time.time() - 99999
        assert mgr.get_session(s.session_id) is None

    def test_get_session_touches(self):
        mgr = SessionManager()
        s = mgr.create_session()
        old_time = s.last_accessed
        time.sleep(0.01)
        mgr.get_session(s.session_id)
        assert s.last_accessed > old_time

    def test_store_data(self):
        mgr = SessionManager()
        s = mgr.create_session()
        mgr.store_data(s.session_id, "key1", "value1")
        assert s.data["key1"] == "value1"

    def test_store_data_invalid_session(self):
        mgr = SessionManager()
        with pytest.raises(KeyError, match="not found or expired"):
            mgr.store_data("nonexistent", "key", "val")

    def test_get_data(self):
        mgr = SessionManager()
        s = mgr.create_session()
        mgr.store_data(s.session_id, "mykey", 42)
        assert mgr.get_data(s.session_id, "mykey") == 42

    def test_get_data_default(self):
        mgr = SessionManager()
        s = mgr.create_session()
        assert mgr.get_data(s.session_id, "missing", "default") == "default"

    def test_get_data_invalid_session(self):
        mgr = SessionManager()
        with pytest.raises(KeyError):
            mgr.get_data("nonexistent", "key")

    def test_delete_session(self):
        mgr = SessionManager()
        s = mgr.create_session()
        mgr.delete_session(s.session_id)
        assert mgr.get_session(s.session_id) is None

    def test_delete_session_nonexistent(self):
        mgr = SessionManager()
        # Should not raise
        mgr.delete_session("nonexistent")

    def test_active_count(self):
        mgr = SessionManager()
        assert mgr.active_count == 0
        mgr.create_session()
        assert mgr.active_count == 1
        mgr.create_session()
        assert mgr.active_count == 2

    def test_cleanup_expired(self):
        mgr = SessionManager()
        s1 = mgr.create_session()
        s2 = mgr.create_session()
        s3 = mgr.create_session()

        # Expire s1 and s3
        s1.last_accessed = time.time() - 99999
        s3.last_accessed = time.time() - 99999

        purged = mgr.cleanup_expired()
        assert purged == 2
        assert mgr.active_count == 1
        assert mgr.get_session(s2.session_id) is not None

    def test_cleanup_none_expired(self):
        mgr = SessionManager()
        mgr.create_session()
        purged = mgr.cleanup_expired()
        assert purged == 0

    def test_store_complex_data(self):
        """Session should hold arbitrary Python objects (DataFrames, etc.)."""
        import pandas as pd

        mgr = SessionManager()
        s = mgr.create_session()
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        mgr.store_data(s.session_id, "dataframe", df)
        retrieved = mgr.get_data(s.session_id, "dataframe")
        assert isinstance(retrieved, pd.DataFrame)
        assert len(retrieved) == 2
