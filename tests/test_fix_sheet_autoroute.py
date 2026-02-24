import unittest

from app.services.reporting import build_fix_rows


class FixSheetAutoRouteTests(unittest.TestCase):
    def test_build_fix_rows_autoroutes_path_from_evidence_and_exports_chain_fields(self):
        issues = [
            {
                "detail": "관리자 승인 실패",
                "Actor": "ADMIN",
                "HandoffKey": "AUTH_FLOW_1",
                "ChainStatus": "FAIL",
                "failureCode": "HTTP_ERROR",
                "증거메타": {
                    "observedUrl": "https://example.com/admin/approve",
                    "screenshotPath": "artifacts/run1/fail.png",
                },
            }
        ]
        rows = build_fix_rows(issues)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.get("경로"), "https://example.com/admin/approve")
        self.assertEqual(row.get("Actor"), "ADMIN")
        self.assertEqual(row.get("HandoffKey"), "AUTH_FLOW_1")
        self.assertEqual(row.get("ChainStatus"), "FAIL")
        self.assertEqual(row.get("ErrorCode"), "HTTP_ERROR")
        self.assertEqual(row.get("Evidence"), "artifacts/run1/fail.png")
        self.assertEqual(row.get("Completeness"), "OK")

    def test_build_fix_rows_marks_missing_completeness(self):
        issues = [{"actual": "generic failure"}]
        row = build_fix_rows(issues)[0]
        self.assertIn("MISSING", str(row.get("Completeness")))
        self.assertIn("HandoffKey", str(row.get("Completeness")))


if __name__ == "__main__":
    unittest.main()
