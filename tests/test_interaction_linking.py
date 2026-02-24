import asyncio
import unittest

from app.services.checklist import _normalize_row, generate_checklist
from fastapi.testclient import TestClient

from app.main import app
from app.services.execute_checklist import _aggregate_chain_status, _normalize_actor, build_execution_graph


class InteractionLinkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

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

    def test_actor_normalization_prefers_user_for_auth_flows(self):
        row = {
            "module": "/auth/otp",
            "구분": "기능",
            "action": "로그인 후 OTP 인증 완료",
            "expected": "마이페이지로 이동",
        }
        self.assertEqual(_normalize_actor(row), "USER")

    def test_actor_normalization_covers_console_admin_routes(self):
        row = {
            "module": "/console/audit-log",
            "구분": "운영",
            "action": "운영자 감사로그 필터 적용",
            "expected": "필터 조건에 맞게 목록 갱신",
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

    def test_build_execution_graph_shape_from_rows(self):
        rows = [
            {"Actor": "USER", "HandoffKey": "AUTH_FLOW", "ChainStatus": "PASS", "action": "로그인", "module": "https://example.com/login"},
            {"Actor": "ADMIN", "HandoffKey": "AUTH_FLOW", "ChainStatus": "FAIL", "action": "승인", "module": "https://example.com/admin"},
            {"Actor": "USER", "action": "마이페이지", "module": "https://example.com/mypage", "실행결과": "PASS"},
        ]
        graph = build_execution_graph(rows, {"AUTH_FLOW": "FAIL"})
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertIn("chainMeta", graph)
        self.assertEqual(len(graph.get("nodes") or []), 3)
        self.assertEqual(len(graph.get("edges") or []), 1)
        self.assertEqual((graph.get("chainMeta") or {}).get("AUTH_FLOW", {}).get("status"), "FAIL")

    def test_execute_graph_endpoint_backward_compatible_aliases(self):
        payload = {
            "rows": [
                {"Actor": "USER", "HandoffKey": "K1", "ChainStatus": "PASS", "action": "A", "module": "https://example.com/a"},
                {"Actor": "ADMIN", "HandoffKey": "K1", "ChainStatus": "PASS", "action": "B", "module": "https://example.com/b"},
            ],
            "chainStatuses": {"K1": "PASS"},
        }
        res = self.client.post("/api/checklist/execute/graph", json=payload)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("graph", body)
        self.assertIn("executionGraph", body)
        self.assertEqual(body.get("graph"), body.get("executionGraph"))
        self.assertEqual((body.get("graph") or {}).get("meta", {}).get("edgeCount"), 1)


if __name__ == "__main__":
    unittest.main()
