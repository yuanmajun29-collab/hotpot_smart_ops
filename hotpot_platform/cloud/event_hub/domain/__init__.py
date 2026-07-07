#!/usr/bin/env python3
"""
领域处理器注册表

每个 domain 模块导出纯函数，通过此文件统一对外暴露。
新增领域 = domain/ 下新增 .py 文件即可，无需改动注册表。

当前注册：
  - health          compute_store_health / _rollup_from_rows / _region_worst_health
  - turnover        turnover_suggestions
  - waste_estimate  compute_waste_estimate
  - loss_risk       compute_loss_risk
  - loss_budget     compute_loss_budget
"""

from hotpot_platform.cloud.event_hub.domain.health import (
    compute_store_health,
    _rollup_from_rows,
    _region_worst_health,
)
from hotpot_platform.cloud.event_hub.domain.turnover import turnover_suggestions
from hotpot_platform.cloud.event_hub.domain.waste_estimate import compute_waste_estimate
from hotpot_platform.cloud.event_hub.domain.loss_risk import compute_loss_risk
from hotpot_platform.cloud.event_hub.domain.loss_budget import compute_loss_budget
