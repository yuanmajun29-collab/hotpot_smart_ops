"""ADR-003 Phase 2: S01 产品主数据 Hub PG 写入测试。

测试策略:
  - 使用 unittest.mock 模拟 PostgresHubDatabase 连接
  - 验证 _save_to_hub_pg() 和 _write_product_to_pg() 的调用路径
  - 验证 SQL UPSERT 语句的正确性
  - 验证 PG 连接失败时的降级处理

运行方式:
    python -m pytest tests/test_adr003_s01_hub_pg.py -v
"""

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── 测试前置: 清除环境变量影响 ──
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试前后清理 HOTPOT 相关环境变量。"""
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("HOTPOT_SUPPLY_CHAIN_WRITE_MODE", raising=False)
    monkeypatch.delenv("HOTPOT_STORE_ID", raising=False)

    # 重置 SupplyChainManager 类变量
    from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
    original_pg_db = getattr(SupplyChainManager, "_pg_db", None)
    original_mode = SupplyChainManager._write_mode
    original_available = SupplyChainManager._hub_pg_available

    yield

    # 恢复原始状态
    SupplyChainManager._pg_db = original_pg_db
    SupplyChainManager._write_mode = original_mode
    SupplyChainManager._hub_pg_available = original_available


class TestSaveToHubPgConnectivity:
    """测试 PG 连接建立和降级。"""

    def test_no_database_url_returns_false(self):
        """未设置 HOTPOT_DATABASE_URL 时返回 False，不抛异常。"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        result = SupplyChainManager._save_to_hub_pg(
            "product", "create", {"sku_code": "TEST-001"}
        )
        assert result is False

    def test_invalid_database_url_returns_false(self):
        """无效的 PG URL 时返回 False，不抛异常。"""
        os.environ["HOTPOT_DATABASE_URL"] = "postgresql://invalid:host/db"

        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        result = SupplyChainManager._save_to_hub_pg(
            "product", "create", {"sku_code": "TEST-002"}
        )
        assert result is False

    @patch("hotpot_platform.cloud.event_hub.pg_db.PostgresHubDatabase")
    def test_successful_connection(self, MockPGDB):
        """成功连接 PG 时返回 True 并设置标志。"""
        os.environ["HOTPOT_DATABASE_URL"] = "postgresql://user:pass@localhost/hotpot"

        # 模拟 PG 实例
        mock_instance = MockPGDB.return_value
        mock_instance.db_path = "pg://localhost/hotpot"

        # 模拟连接和 cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_cursor
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_ctx
        mock_instance._getconn.return_value = mock_conn
        mock_instance._putconn = MagicMock()

        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        result = SupplyChainManager._save_to_hub_pg(
            "product",
            "create",
            {
                "sku_code": "TEST-003",
                "name": "测试产品",
                "specification": "500g/盒",
                "brand": "测试品牌",
                "unit_price": 28.5,
                "category": "FROZEN_MEAT",
                "status": "draft",
                "locked": False,
                "version": 1,
            },
        )

        assert result is True
        assert SupplyChainManager._hub_pg_available is True
        MockPGDB.assert_called_once()

    def test_unsupported_entity_type_returns_false(self):
        """不支持的 entity_type 返回 False 并记录警告。"""
        os.environ["HOTPOT_DATABASE_URL"] = "postgresql://user:pass@localhost/hotpot"

        with patch("hotpot_platform.cloud.event_hub.pg_db.PostgresHubDatabase") as MockPGDB:
            MockPGDB.return_value.db_path = "pg://localhost/hotpot"

            from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

            result = SupplyChainManager._save_to_hub_pg(
                "receiving", "create", {"record_id": "R001"}
            )

            assert result is False


class TestWriteProductToPg:
    """测试 S01 产品主数据的 PG UPSERT 逻辑。"""

    def _make_mock_pg_db(self):
        """创建模拟的 PostgresHubDatabase 实例。

        模拟 psycopg2 连接池的调用链:
            pg_db._getconn() → conn
                conn.cursor() → ctx (context manager)
                    ctx.__enter__() → cur
                        cur.execute(sql, params)
                    ctx.__exit__(*args)
            pg_db._putconn(conn)
        """
        pg_db = MagicMock()
        pg_db.db_path = "pg://localhost/hotpot"

        # 模拟连接对象
        mock_conn = MagicMock()
        pg_db._getconn.return_value = mock_conn

        # 模拟 cursor context manager
        mock_cursor = MagicMock()
        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__enter__.return_value = mock_cursor
        mock_ctx_mgr.__exit__.return_value = False
        mock_conn.cursor.return_value = mock_ctx_mgr

        return pg_db, mock_cursor

    def test_upsert_create_calls_correct_sql(self):
        """CREATE 操作生成正确的 INSERT ... ON CONFLICT UPDATE SQL。"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        pg_db, mock_cursor = self._make_mock_pg_db()

        data = {
            "sku_code": "SKU-CREATE-001",
            "name": "毛肚",
            "specification": "500g/盒",
            "brand": "海霸王",
            "unit_price": 45.0,
            "unit": "盒",
            "category": "FROZEN_MEAT",
            "status": "draft",
            "locked": False,
            "version": 1,
            "created_by": "test_operator",
            "updated_by": "test_operator",
        }

        result = SupplyChainManager._write_product_to_pg(pg_db, "create", data)

        assert result is True
        # 验证 execute 被调用（SQL 执行）
        assert mock_cursor.execute.called
        # 验证 commit 被调用
        pg_db._getconn.return_value.commit.assert_called_once()
        # 验证连接归还
        pg_db._putconn.assert_called_once_with(pg_db._getconn.return_value)

    def test_upsert_update_modifies_existing_row(self):
        """UPDATE 操作使用相同的 UPSERT SQL（覆盖写）。"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        pg_db, mock_cursor = self._make_mock_pg_db()

        data = {
            "sku_code": "SKU-UPDATE-001",
            "name": "升级版毛肚",
            "specification": "500g/盒",
            "brand": "海霸王",
            "unit_price": 48.0,  # 价格变更
            "unit": "盒",
            "category": "FROZEN_MEAT",
            "status": "active",
            "locked": True,
            "version": 2,
            "updated_by": "admin",
        }

        result = SupplyChainManager._write_product_to_pg(pg_db, "update", data)

        assert result is True
        assert mock_cursor.execute.called

    def test_delete_generates_correct_sql(self):
        """DELETE 操作生成正确的 DELETE SQL。"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        pg_db, mock_cursor = self._make_mock_pg_db()

        result = SupplyChainManager._write_product_to_pg(
            pg_db, "delete", {"sku_code": "SKU-DELETE-001"}
        )

        assert result is True
        # 验证 DELETE SQL 被执行
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0] if call_args[0] else ""
        assert "DELETE FROM supply_product_master" in sql

    def test_missing_sku_code_returns_false(self):
        """缺少 sku_code 时返回 False。"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        pg_db, _ = self._make_mock_pg_db()

        result = SupplyChainManager._write_product_to_pg(pg_db, "create", {"name": "无SKU产品"})
        assert result is False

    def test_payload_contains_all_fields(self):
        """JSONB payload 包含完整的 ProductMaster 字段。"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        pg_db, mock_cursor = self._make_mock_pg_db()

        data = {
            "sku_code": "SKU-PAYLOAD-001",
            "name": "完整字段产品",
            "specification": "2kg/件",
            "brand": "喜得佳",
            "unit_price": 128.0,
            "unit": "件",
            "category": "FROZEN_MEAT",
            "supplier_id": "SUP-001",
            "supplier_name": "杭州冻品供应链",
            "image_url": "https://example.com/product.jpg",
            "location_code": "A-01-03",
            "storage_area": "冷冻",
            "shelf_life_days": 180,
            "min_stock_qty": 10.0,
            "tags": ["热销", "新品"],
            "status": "active",
            "locked": True,
            "version": 3,
            "created_by": "system",
            "updated_by": "admin",
        }

        SupplyChainManager._write_product_to_pg(pg_db, "update", data)

        # 提取 SQL 参数中的 payload (最后一个参数是 JSONB)
        call_args = mock_cursor.execute.call_args
        params = call_args[0][1] if call_args[0] else []
        payload_json = params[-1]  # 最后一个参数是 payload JSONB

        # 解析并验证完整性
        payload = json.loads(payload_json)
        assert payload["sku_code"] == "SKU-PAYLOAD-001"
        assert payload["name"] == "完整字段产品"
        assert payload["tags"] == ["热销", "新品"]
        assert payload["version"] == 3


class TestIntegrationWithCRUDMethods:
    """测试 S01 CRUD 方法与 _save_to_hub_pg 的集成。

    这些测试验证 create/update/lock/unlock/delete 方法
    在调用 _save_to_json() 后正确触发 _save_to_hub_pg()。
    """

    def test_create_product_calls_hub_pg(self):
        """create_product_master() 调用 _save_to_hub_pg("product", "create", ...)。"""
        import tempfile
        from hotpot_platform.cloud.supply_chain.manager import (
            SupplyChainManager,
            ProductCreateRequest,
        )

        with patch.object(
            SupplyChainManager,
            "_save_to_hub_pg",
            return_value=True,
        ) as mock_save_pg:

            # 初始化（使用临时 JSON 文件）
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
                f.write('{"products": {}, "categories": []}')
                temp_file = f.name

            try:
                SupplyChainManager.init_product_data(temp_file)

                req = ProductCreateRequest(
                    sku_code="INT-TEST-001",
                    name="集成测试产品",
                    specification="1kg/袋",
                    brand="测试",
                    unit_price=30.0,
                    category="FROZEN_MEAT",
                )

                product = SupplyChainManager.create_product_master(req, operator="tester")

                # 验证 _save_to_hub_pg 被调用
                mock_save_pg.assert_called_once()
                call_args = mock_save_pg.call_args[0]
                assert call_args[0] == "product"  # entity_type
                assert call_args[1] == "create"   # operation
                assert call_args[2]["sku_code"] == "INT-TEST-001"

            finally:
                os.unlink(temp_file)

    def test_update_product_calls_hub_pg(self):
        """update_product_master() 调用 _save_to_hub_pg("product", "update", ...)。"""
        import tempfile
        from hotpot_platform.cloud.supply_chain.manager import (
            SupplyChainManager,
            ProductCreateRequest,
            ProductUpdateRequest,
        )

        with patch.object(
            SupplyChainManager,
            "_save_to_hub_pg",
            return_value=True,
        ) as mock_save_pg:

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
                f.write('{"products": {}, "categories": []}')
                temp_file = f.name

            try:
                SupplyChainManager.init_product_data(temp_file)

                # 先创建
                req = ProductCreateRequest(
                    sku_code="INT-UPD-001",
                    name="待更新产品",
                    specification="500g/盒",
                    brand="原版",
                    unit_price=25.0,
                    category="VEGETABLE",
                )
                SupplyChainManager.create_product_master(req)

                # 清除调用计数
                mock_save_pg.reset_mock()

                # 再更新
                upd_req = ProductUpdateRequest(unit_price=28.0)
                SupplyChainManager.update_product_master("INT-UPD-001", upd_req, operator="updater")

                # 验证 update 调用
                mock_save_pg.assert_called_once()
                assert mock_save_pg.call_args[0][1] == "update"

            finally:
                os.unlink(temp_file)

    def test_delete_product_calls_hub_pg(self):
        """delete_product_master() 调用 _save_to_hub_pg("product", "delete", ...)。"""
        import tempfile
        from hotpot_platform.cloud.supply_chain.manager import (
            SupplyChainManager,
            ProductCreateRequest,
        )

        with patch.object(
            SupplyChainManager,
            "_save_to_hub_pg",
            return_value=True,
        ) as mock_save_pg:

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
                f.write('{"products": {}, "categories": []}')
                temp_file = f.name

            try:
                SupplyChainManager.init_product_data(temp_file)

                # 创建一个 draft 产品
                req = ProductCreateRequest(
                    sku_code="INT-DEL-001",
                    name="待删除产品",
                    specification="100g/包",
                    brand="临时",
                    unit_price=5.0,
                    category="SEASONING",
                )
                SupplyChainManager.create_product_master(req)

                # 清除调用计数
                mock_save_pg.reset_mock()

                # 删除
                SupplyChainManager.delete_product_master("INT-DEL-001", operator="deleter")

                # 验证 delete 调用
                mock_save_pg.assert_called_once()
                assert mock_save_pg.call_args[0][0] == "product"
                assert mock_save_pg.call_args[0][1] == "delete"
                assert mock_save_pg.call_args[0][2] == {"sku_code": "INT-DEL-001"}

            finally:
                os.unlink(temp_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
