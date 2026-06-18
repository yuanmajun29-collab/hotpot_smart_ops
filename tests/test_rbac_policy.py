"""Backend/frontend RBAC policy alignment."""

from __future__ import annotations

import json
from pathlib import Path

from cloud.event_hub.rbac import ROLE_ACTIONS, data_scope_for_role


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_backend_actions_match_dashboard_rbac_matrix():
    matrix = json.loads(
        (PROJECT_ROOT / "dashboard" / "assets" / "rbac.json").read_text(encoding="utf-8")
    )
    dashboard_roles = matrix["roles"]

    for role, config in dashboard_roles.items():
        assert role in ROLE_ACTIONS
        assert set(ROLE_ACTIONS[role]) == set(config.get("actions", []))


def test_role_data_scopes_cover_phase1_personas():
    assert data_scope_for_role("店长") == "store"
    assert data_scope_for_role("前厅领班") == "store"
    assert data_scope_for_role("厨师长") == "store"
    assert data_scope_for_role("收货员") == "store"
    assert data_scope_for_role("区域督导") == "region"
    assert data_scope_for_role("总部PMO") == "national"
    assert data_scope_for_role("集团决策者") == "national"


def test_auth_mode_reads_env_at_call_time(monkeypatch):
    """auth_mode() must reflect runtime env changes, not an import-time cache."""
    from cloud.event_hub.auth import auth_mode

    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
    assert auth_mode() == "strict"

    monkeypatch.delenv("HOTPOT_AUTH_MODE", raising=False)
    assert auth_mode() == "demo"
