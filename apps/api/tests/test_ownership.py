"""Session ownership tests (A2 — IDOR P1-2).

Covers the `get_owned_session` dependency and the Session.owner_user_id
plumbing. Router-level rewires happen in bloc E2; these tests exercise the
helpers directly so the behaviour is locked in regardless of router code.
"""

from __future__ import annotations

import secrets

import pytest

from app.auth import UserRecord, get_owned_session, user_store
from app.session import session_manager
from app.security import (
    _ensure_safe_segment,
    session_root,
    validate_path,
    validate_session_path,
)
from fastapi import HTTPException


def _make_user(email: str | None = None) -> UserRecord:
    """Create a real user via the in-memory user_store."""
    email = email or f"own+{secrets.token_hex(4)}@example.com"
    return user_store.register(email, "supersecret123")


def _del_user(user: UserRecord) -> None:
    # Drop the user out of the in-memory store between tests.
    store_users = getattr(user_store, "_users", None)
    if store_users is not None:
        store_users.pop(user.email, None)


class TestSessionOwnership:
    def test_session_carries_owner_user_id(self):
        user = _make_user()
        try:
            s = session_manager.create_session(mode="TV", owner_user_id=user.user_id)
            assert s.owner_user_id == user.user_id
            assert isinstance(s.session_id, str) and len(s.session_id) == 32
        finally:
            session_manager.delete_session(s.session_id)
            _del_user(user)

    def test_get_owned_session_returns_session_for_owner(self):
        user = _make_user()
        try:
            s = session_manager.create_session(mode="TV", owner_user_id=user.user_id)
            got = get_owned_session(session_id=s.session_id, current_user=user)
            assert got.session_id == s.session_id
            assert got.owner_user_id == user.user_id
        finally:
            session_manager.delete_session(s.session_id)
            _del_user(user)

    def test_get_owned_session_returns_404_for_other_user(self):
        alice = _make_user("alice@example.com")
        bob = _make_user("bob@example.com")
        s_alice = session_manager.create_session(mode="TV", owner_user_id=alice.user_id)
        try:
            with pytest.raises(HTTPException) as exc:
                get_owned_session(session_id=s_alice.session_id, current_user=bob)
            assert exc.value.status_code == 404
            # Crucially, NOT 403 — we don't want to leak existence.
            assert exc.value.status_code != 403
        finally:
            session_manager.delete_session(s_alice.session_id)
            _del_user(alice)
            _del_user(bob)

    def test_get_owned_session_returns_404_for_missing_session(self):
        user = _make_user()
        try:
            with pytest.raises(HTTPException) as exc:
                get_owned_session(session_id="nonexistent_session_id", current_user=user)
            assert exc.value.status_code == 404
        finally:
            _del_user(user)

    def test_legacy_session_without_owner_is_accessible(self):
        """Sessions created before A2 (owner_user_id == "") stay accessible.

        Keeps the migration safe — old sessions still load until they expire
        via their TTL. New sessions created after A2 are always owned.
        """
        user = _make_user()
        s = session_manager.create_session(mode="TV", owner_user_id="")
        try:
            got = get_owned_session(session_id=s.session_id, current_user=user)
            assert got.session_id == s.session_id
        finally:
            session_manager.delete_session(s.session_id)
            _del_user(user)


class TestPathConfinement:
    """A5: paths must stay inside `WORKSPACE_ROOT/{user_id}/{session_id}/`."""

    def test_session_root_creates_per_user_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.security.get_settings",
            lambda: type("S", (), {"WORKSPACE_ROOT": str(tmp_path)})(),
        )
        root = session_root("user123", "sessabc")
        assert root.exists()
        # Cross-platform path check (Windows uses backslash).
        assert root.parts[-2] == "user123"
        assert root.parts[-1] == "sessabc"

    def test_validate_path_blocks_escape(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            validate_path("../../etc/passwd", allowed_root=str(tmp_path))
        assert exc.value.status_code == 403

    def test_validate_path_blocks_nul_byte(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            validate_path("safe\x00name", allowed_root=str(tmp_path))
        assert exc.value.status_code == 400

    def test_validate_path_accepts_inside(self, tmp_path):
        target = tmp_path / "inside" / "file.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
        resolved = validate_path(str(target), allowed_root=str(tmp_path))
        assert resolved == target.resolve()

    def test_validate_session_path_namespaces_per_user(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.security.get_settings",
            lambda: type("S", (), {"WORKSPACE_ROOT": str(tmp_path)})(),
        )
        root = session_root("u1", "s1")
        inside = root / "models" / "model.keras"
        inside.parent.mkdir(parents=True)
        inside.write_bytes(b"x")

        resolved = validate_session_path(str(inside), user_id="u1", session_id="s1")
        assert resolved == inside.resolve()

        # Trying to access another user's tree must fail.
        other_root = session_root("u2", "s1")
        other_file = other_root / "models" / "model.keras"
        other_file.parent.mkdir(parents=True)
        other_file.write_bytes(b"x")
        with pytest.raises(HTTPException) as exc:
            validate_session_path(str(other_file), user_id="u1", session_id="s1")
        assert exc.value.status_code == 403

    def test_session_root_rejects_traversal_chars(self):
        with pytest.raises(HTTPException) as exc:
            _ensure_safe_segment("../etc", "user_id")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _ensure_safe_segment("a/b", "session_id")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _ensure_safe_segment("", "user_id")
        assert exc.value.status_code == 400


class TestPickleRefused:
    """A3: legacy pickle blobs in Redis must raise instead of executing."""

    def test_deserialize_pickle_blob_refused(self):
        from app.session import RedisBackend

        # Synthetic blob with the legacy magic prefix — never feed real pickle
        # bytes here, the whole point is to prove they are NOT unpickled.
        blob = b"__DFPKL__" + b"cposix\nsystem\np0\n(S'echo pwned'\np1\ntp2\nRp3\n."
        with pytest.raises(ValueError, match="legacy pickle blob refused"):
            RedisBackend._deserialize_value(blob)

    def test_df_with_dict_cell_serialises_via_parquet(self):
        import io
        import pandas as pd
        from app.session import _df_to_parquet_safe

        df = pd.DataFrame({
            "id": [1, 2],
            "geometry": [{"type": "Point", "coordinates": [0, 0]}, None],
        })
        data = _df_to_parquet_safe(df)
        out = pd.read_parquet(io.BytesIO(data))
        assert len(out) == 2
        # Dict was cast to JSON str; never pickled.
        assert isinstance(out.loc[0, "geometry"], str)


# ---------------------------------------------------------------------------
# T2 — IDOR cross-tenant via HTTP routers
# ---------------------------------------------------------------------------
#
# Ces tests vont au-dela des helpers (get_owned_session / require_owned_session)
# pour valider que les ROUTERS HTTP refusent bien le cross-tenant.
#
# NOTE : ils dependent du fix de l'agent A1 (securite) qui plugue
# `require_owned_session` partout. Si A1 n'a pas fini, certains peuvent
# echouer avec 200 au lieu de 403/404.

class TestIDORCrossTenantHTTP:
    """User B ne doit JAMAIS pouvoir acceder a la session de User A."""

    async def _register_and_login(self, client, email: str, password: str = "test-pass-12345") -> dict:
        """Register + login un user via le client async, retourne le token."""
        r = await client.post("/api/auth/register", json={"email": email, "password": password})
        # 201 si nouveau, 409 si deja existe (re-login OK dans ce cas)
        assert r.status_code in (200, 201, 409), r.text
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()

    @pytest.mark.asyncio
    async def test_upload_creates_owned_session(self, authenticated_client, csv_content):
        """POST /api/upload retourne une session avec owner_user_id non-vide."""
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        assert r.status_code == 200
        sid = r.json()["session_id"]
        # Verifier au niveau backend que la session a bien un owner
        from app.session import session_manager
        sess = session_manager.get_session(sid)
        assert sess is not None
        assert sess.owner_user_id  # non-vide
        # L'owner doit correspondre a l'user de authenticated_client
        assert sess.owner_user_id == authenticated_client.user_id

    @pytest.mark.asyncio
    async def test_user_b_cannot_access_user_a_session(self, client, csv_content):
        """User A cree une session ; User B (autre token) -> 404 sur acces."""
        # User A : register + login + upload
        suffix_a = secrets.token_hex(4)
        tok_a = await self._register_and_login(client, f"alice+{suffix_a}@example.com")
        client.headers.update({"Authorization": f"Bearer {tok_a['access_token']}"})
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        assert r.status_code == 200
        sid_a = r.json()["session_id"]

        # User B : autre register + login
        suffix_b = secrets.token_hex(4)
        tok_b = await self._register_and_login(client, f"bob+{suffix_b}@example.com")
        client.headers.update({"Authorization": f"Bearer {tok_b['access_token']}"})

        # User B tente d'acceder a la session A
        # On essaie plusieurs routes proteges par require_owned_session
        # (au moins une doit refuser le cross-tenant)
        # /api/sessions/{sid} (si la route existe)
        # /api/mapping/auto
        r_b = await client.post(
            "/api/mapping/auto",
            json={"session_id": sid_a},
        )
        # Accept 404 (no leak) ou 403 (explicit forbid). NE PAS accepter 200.
        assert r_b.status_code in (403, 404), (
            f"IDOR leak: user B got status={r_b.status_code} for user A's session"
        )

    @pytest.mark.asyncio
    async def test_mapping_auto_requires_ownership(self, client, csv_content):
        """User B -> 403/404 sur /api/mapping/auto avec session_id de user A."""
        # User A
        suffix_a = secrets.token_hex(4)
        tok_a = await self._register_and_login(client, f"alice2+{suffix_a}@example.com")
        client.headers.update({"Authorization": f"Bearer {tok_a['access_token']}"})
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid_a = r.json()["session_id"]

        # User B
        suffix_b = secrets.token_hex(4)
        tok_b = await self._register_and_login(client, f"bob2+{suffix_b}@example.com")
        client.headers.update({"Authorization": f"Bearer {tok_b['access_token']}"})
        r_b = await client.post(
            "/api/mapping/auto",
            json={"session_id": sid_a},
        )
        assert r_b.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_models_list_requires_ownership(self, client, csv_content):
        """User B -> 403/404 sur /api/models/list?session_id=<session de A>."""
        suffix_a = secrets.token_hex(4)
        tok_a = await self._register_and_login(client, f"alice3+{suffix_a}@example.com")
        client.headers.update({"Authorization": f"Bearer {tok_a['access_token']}"})
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid_a = r.json()["session_id"]

        suffix_b = secrets.token_hex(4)
        tok_b = await self._register_and_login(client, f"bob3+{suffix_b}@example.com")
        client.headers.update({"Authorization": f"Bearer {tok_b['access_token']}"})
        r_b = await client.get(f"/api/models/list?session_id={sid_a}")
        assert r_b.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_path_traversal_session_id(self, authenticated_client):
        """session_id avec traversal ('../../etc') -> 400/404/422 (jamais 200)."""
        # Plusieurs routes (au moins une rejette explicitement)
        # /api/sessions/{path} ne va pas matcher car aucune session existe ;
        # mais on doit avoir 404 et NOT 500 stack trace.
        for endpoint, method, kwargs in [
            ("/api/mapping/auto", "post", {"json": {"session_id": "../../etc/passwd"}}),
            ("/api/models/list?session_id=../../etc", "get", {}),
        ]:
            r = await getattr(authenticated_client, method)(endpoint, **kwargs)
            # Pas de 200 et pas de 500 (= leak ou stack trace).
            assert r.status_code in (400, 403, 404, 422), (
                f"path traversal on {endpoint}: status={r.status_code}"
            )
