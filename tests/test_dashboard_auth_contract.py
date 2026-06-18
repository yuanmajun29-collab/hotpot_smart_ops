"""Dashboard auth contract regression tests."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_login_does_not_send_client_chosen_role():
    core_js = (PROJECT_ROOT / "dashboard" / "assets" / "core.js").read_text(encoding="utf-8")
    login_html = (PROJECT_ROOT / "dashboard" / "login.html").read_text(encoding="utf-8")

    assert "async function hubLogin(username, password, storeIdVal)" in core_js
    assert "payload.role" not in core_js
    assert "HotpotApp.hubLogin(username, password, selectedStoreId)" in login_html


def test_dashboard_login_uses_server_role_after_success():
    login_html = (PROJECT_ROOT / "dashboard" / "login.html").read_text(encoding="utf-8")

    assert "角色由服务端按账号判定" in login_html
    assert "const role = user.role; // server is authoritative" in login_html
    assert "user.role || role" not in login_html
    assert "role: user.role || role" not in login_html
