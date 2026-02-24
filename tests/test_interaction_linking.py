import asyncio
import unittest

from app.services.checklist import generate_checklist
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

    def test_chain_status_aggregation(self):
        self.assertEqual(_aggregate_chain_status(["PASS", "PASS"]), "PASS")
        self.assertEqual(_aggregate_chain_status(["PASS", "BLOCKED"]), "BLOCKED")
        self.assertEqual(_aggregate_chain_status(["PASS", "FAIL"]), "FAIL")


if __name__ == "__main__":
    unittest.main()
