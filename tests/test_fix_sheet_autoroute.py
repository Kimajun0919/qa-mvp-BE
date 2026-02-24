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
        self.assertIn("field:", str(row.get("ValidationPoint") or ""))
        self.assertEqual(row.get("Completeness"), "OK")

    def test_build_fix_rows_marks_missing_completeness(self):
        issues = [{"actual": "generic failure"}]
        row = build_fix_rows(issues)[0]
        self.assertIn("MISSING", str(row.get("Completeness")))
        self.assertIn("HandoffKey", str(row.get("Completeness")))

    def test_build_fix_rows_enforces_single_validation_point_per_issue(self):
        issues = [
            {
                "actual": "폼 제출 실패",
                "decompositionRows": [
                    {"kind": "FIELD", "field": "legacy-field", "action": "legacy-action", "assertion": {"expected": "x", "observed": "y"}},
                    {"kind": "VALIDATION_POINT", "field": "order-form", "action": "submit-empty-form", "assertion": {"expected": "필수값 오류", "observed": "오류 미노출"}},
                    {"kind": "VALIDATION_POINT", "field": "order-form-2", "action": "click-save", "assertion": {"expected": "저장", "observed": "실패"}},
                ],
            }
        ]
        row = build_fix_rows(issues)[0]
        vp = str(row.get("ValidationPoint") or "")
        self.assertIn("field:order-form", vp)
        self.assertIn("action:submit-empty-form", vp)
        self.assertNotIn("order-form-2", vp)


if __name__ == "__main__":
    unittest.main()
