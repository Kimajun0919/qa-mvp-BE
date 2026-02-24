import asyncio
import unittest

from app.services.checklist import _normalize_row, generate_checklist
from app.services.execute_checklist import _aggregate_chain_status, _normalize_actor


class InteractionLinkingTests(unittest.TestCase):
    def test_checklist_rows_include_linking_fields_backward_compatible(self):
        out = asyncio.run(
            generate_checklist(
                screen="https://example.com/admin",
                context="interaction linking",
                include_auth=True,
                provider="__no_llm__",
                max_rows=12,
            )
        )
        self.assertTrue(out.get("ok"))
        rows = out.get("rows") or []
        self.assertGreater(len(rows), 0)
        first = rows[0]
        self.assertIn("Actor", first)
        self.assertIn("HandoffKey", first)
        self.assertIn("ChainStatus", first)
        self.assertIn(first.get("Actor"), {"USER", "ADMIN"})

    def test_actor_normalization_defaults_to_user(self):
        self.assertEqual(_normalize_actor({}), "USER")
        self.assertEqual(_normalize_actor({"Actor": "admin"}), "ADMIN")
        self.assertEqual(_normalize_actor({"Actor": "unknown"}), "USER")

    def test_actor_normalization_infers_admin_from_route_role_context(self):
        row = {
            "module": "/admin/users",
            "구분": "권한",
            "action": "권한 없는 계정으로 권한승격 시도",
            "expected": "정책에 따라 차단",
        }
        self.assertEqual(_normalize_actor(row), "ADMIN")

    def test_normalize_row_infers_actor_and_handoff_key_for_linking(self):
        row = _normalize_row(
            {
                "화면": "/admin/roles",
                "구분": "회귀",
                "action": "관리자 변경 후 사용자 화면 반영 상태 확인",
                "expected": "권한 변경 사항 반영",
            },
            default_screen="/admin/roles",
        )
        self.assertEqual(row.get("Actor"), "ADMIN")
        self.assertEqual(row.get("HandoffKey"), "USER_ROLE_SYNC")

    def test_chain_status_aggregation(self):
        self.assertEqual(_aggregate_chain_status(["PASS", "PASS"]), "PASS")
        self.assertEqual(_aggregate_chain_status(["PASS", "BLOCKED"]), "BLOCKED")
        self.assertEqual(_aggregate_chain_status(["PASS", "FAIL"]), "FAIL")


if __name__ == "__main__":
    unittest.main()
