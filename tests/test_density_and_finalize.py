import asyncio
import unittest

from app.services.checklist import generate_checklist
from app.services.final_output import _to_detail_rows
from app.main import _extract_execute_payload


class DensityAndFinalizeTests(unittest.TestCase):
    def test_heuristic_density_screen_section(self):
        out = asyncio.run(
            generate_checklist(
                screen="https://example.com/admin",
                context="form table",
                include_auth=True,
                provider="__no_llm__",
                max_rows=40,
            )
        )
        rows = out.get("rows") or []
        self.assertGreaterEqual(len(rows), 10)
        modules = [str(r.get("module") or "") for r in rows]
        self.assertTrue(any("::" in m for m in modules))

    def test_finalize_keeps_full_decomposition_shape(self):
        items = [
            {
                "테스트시나리오": "폼 제출",
                "실행결과": "FAIL",
                "decompositionRows": [
                    {"kind": "FIELD", "field": "https://example.com::폼", "action": "detect-surface", "assertion": {}, "evidence": {}},
                    {"kind": "ACTION", "field": "https://example.com::폼", "action": "submit-empty-form", "assertion": {}, "evidence": {}},
                ],
            }
        ]
        rows = _to_detail_rows(items)
        note = rows[0].get("비고") or ""
        for token in ["field:", "action:", "assert:", "error:", "evidence:"]:
            self.assertIn(token, note)

    def test_execute_payload_server_safe_defaults(self):
        cfg = _extract_execute_payload({"rows": [{"화면": "https://example.com", "테스트시나리오": "렌더"}]})
        self.assertFalse(cfg["allow_risky_actions"])
        self.assertEqual(cfg["exhaustive"], False)
        self.assertLessEqual(cfg["exhaustive_depth"], 2)


if __name__ == "__main__":
    unittest.main()
