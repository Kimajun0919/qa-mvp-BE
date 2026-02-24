import unittest

from fastapi.testclient import TestClient

from app.main import app, execute_jobs, native_analysis_store
from app.services.analyze import _classify_role


class CleanupAndRouteRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_delete_analysis_cleanup_route_available(self):
        analysis_id = "analysis_cleanup_case"
        native_analysis_store[analysis_id] = {"analysis": {"analysisId": analysis_id, "baseUrl": "https://example.com"}}

        res = self.client.delete(f"/api/analysis/{analysis_id}")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("analysisId"), analysis_id)
        self.assertNotIn(analysis_id, native_analysis_store)

    def test_delete_execute_job_cleanup_route_available(self):
        job_id = "job_cleanup_case"
        execute_jobs[job_id] = {"ok": True, "status": "done"}

        res = self.client.delete(f"/api/checklist/execute/status/{job_id}")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("deleted"))
        self.assertNotIn(job_id, execute_jobs)

    def test_route_role_mapping_covers_common_gaps(self):
        self.assertEqual(_classify_role("/admin/users", "User role management"), "DASHBOARD")
        self.assertEqual(_classify_role("/account/profile", "My account"), "CHECKOUT")
        self.assertEqual(_classify_role("/signup", "Create account"), "LOGIN")


if __name__ == "__main__":
    unittest.main()
