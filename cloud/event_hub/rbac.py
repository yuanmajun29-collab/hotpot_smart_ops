"""Role policy helpers shared by auth and tests.

Phase 1 keeps RBAC in code plus dashboard/assets/rbac.json. Centralizing the
backend policy here keeps the later DB-backed roles migration smaller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


STORE_SCOPE = "store"
REGION_SCOPE = "region"
NATIONAL_SCOPE = "national"

WRITE_NONE = "none"
WRITE_OWN = "own"
WRITE_OWN_OR_ALL = "own_or_all"
WRITE_ALL = "all"


@dataclass(frozen=True)
class RolePolicy:
    actions: Tuple[str, ...]
    data_scope: str = STORE_SCOPE
    can_admin: bool = False
    read_all_stores: bool = False
    write_scope: str = WRITE_NONE


ROLE_POLICIES: Dict[str, RolePolicy] = {
    "店长": RolePolicy(
        actions=("ack", "table_correct", "receiving_submit", "sop_assign", "report_generate"),
        write_scope=WRITE_OWN_OR_ALL,
    ),
    "前厅领班": RolePolicy(
        actions=("ack", "table_correct"),
        write_scope=WRITE_OWN_OR_ALL,
    ),
    "厨师长": RolePolicy(
        actions=("ack", "receiving_submit", "sop_assign"),
        write_scope=WRITE_OWN_OR_ALL,
    ),
    "收货员": RolePolicy(
        actions=("receiving_submit",),
        write_scope=WRITE_OWN,
    ),
    "区域督导": RolePolicy(
        actions=("ack", "sop_assign", "report_generate"),
        data_scope=REGION_SCOPE,
        read_all_stores=True,
        write_scope=WRITE_ALL,
    ),
    "总部PMO": RolePolicy(
        actions=("report_generate", "sop_assign", "admin_write"),
        data_scope=NATIONAL_SCOPE,
        can_admin=True,
    ),
    "总部 IT": RolePolicy(
        actions=("report_generate", "sop_assign", "admin_write"),
        data_scope=NATIONAL_SCOPE,
        can_admin=True,
    ),
    "集团决策者": RolePolicy(
        actions=(),
        data_scope=NATIONAL_SCOPE,
        read_all_stores=True,
    ),
    "edge": RolePolicy(
        actions=("table_correct", "receiving_submit", "sop_assign"),
        write_scope=WRITE_OWN_OR_ALL,
    ),
}


ROLE_ACTIONS: Dict[str, Tuple[str, ...]] = {
    role: policy.actions for role, policy in ROLE_POLICIES.items()
}


def role_policy(role: str) -> RolePolicy:
    return ROLE_POLICIES.get(role, RolePolicy(actions=()))


def data_scope_for_role(role: str) -> str:
    return role_policy(role).data_scope


def role_can_admin(role: str) -> bool:
    return role_policy(role).can_admin


def role_can_read_store(role: str, token_store_id: str, target_store_id: str) -> bool:
    if token_store_id == "*":
        return True
    if role_policy(role).read_all_stores:
        return True
    return token_store_id == target_store_id


def role_can_write_store(role: str, token_store_id: str, target_store_id: str) -> bool:
    scope = role_policy(role).write_scope
    if scope == WRITE_ALL:
        return True
    if scope == WRITE_OWN_OR_ALL:
        return token_store_id == "*" or token_store_id == target_store_id
    if scope == WRITE_OWN:
        return token_store_id == target_store_id
    return False


def role_can_action(role: str, action: str) -> bool:
    return action in role_policy(role).actions
