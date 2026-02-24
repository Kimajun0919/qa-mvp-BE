import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, execute_jobs, native_analysis_store
from app.services.analyze import _classify_role
from app.services.storage import get_bundle, save_analysis


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
        self.assertTrue(body.get("deleted"))
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

    def test_delete_analysis_cleanup_route_reports_deleted_when_db_only(self):
        analysis_id = "analysis_cleanup_db_only"
        save_analysis(analysis_id, "https://example.com", [{"url": "https://example.com"}], [], [])
        native_analysis_store.pop(analysis_id, None)

        res = self.client.delete(f"/api/analysis/{analysis_id}")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("deleted"))

        res2 = self.client.delete(f"/api/analysis/{analysis_id}")
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.json().get("deleted"))

    def test_chain_cleanup_sequence_cleans_all_created_entities(self):
        analysis_id = "analysis_chain_cleanup"
        job_id = "job_chain_cleanup"

        save_analysis(analysis_id, "https://example.com", [{"url": "https://example.com/flow"}], [], [])
        native_analysis_store[analysis_id] = {"analysis": {"analysisId": analysis_id, "baseUrl": "https://example.com"}}
        execute_jobs[job_id] = {"ok": True, "status": "done"}

        analysis_res = self.client.delete(f"/api/analysis/{analysis_id}")
        self.assertEqual(analysis_res.status_code, 200)
        self.assertTrue(analysis_res.json().get("deleted"))

        job_res = self.client.delete(f"/api/checklist/execute/status/{job_id}")
        self.assertEqual(job_res.status_code, 200)
        self.assertTrue(job_res.json().get("deleted"))

        self.assertNotIn(analysis_id, native_analysis_store)
        self.assertNotIn(job_id, execute_jobs)

    def test_cleanup_chain_endpoint_cleans_user_admin_entities_without_residuals(self):
        user_analysis_id = "analysis_user_chain_cleanup"
        admin_analysis_id = "analysis_admin_chain_cleanup"
        user_job_id = "job_user_chain_cleanup"
        admin_job_id = "job_admin_chain_cleanup"

        save_analysis(user_analysis_id, "https://example.com", [{"url": "https://example.com/user"}], [], [])
        save_analysis(admin_analysis_id, "https://example.com/admin", [{"url": "https://example.com/admin"}], [], [])
        native_analysis_store[user_analysis_id] = {"analysis": {"analysisId": user_analysis_id, "baseUrl": "https://example.com"}}
        native_analysis_store[admin_analysis_id] = {"analysis": {"analysisId": admin_analysis_id, "baseUrl": "https://example.com/admin"}}
        execute_jobs[user_job_id] = {"ok": True, "status": "done"}
        execute_jobs[admin_job_id] = {"ok": True, "status": "done"}

        artifact_path = Path("out") / "chain_cleanup_artifact.tmp"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("temp", encoding="utf-8")

        res = self.client.post(
            "/api/cleanup/chain",
            json={
                "analysisIds": [user_analysis_id, admin_analysis_id],
                "jobIds": [user_job_id, admin_job_id],
                "artifactPaths": [str(artifact_path)],
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("residual"), {"analysisIds": [], "jobIds": [], "artifactPaths": []})

        self.assertNotIn(user_analysis_id, native_analysis_store)
        self.assertNotIn(admin_analysis_id, native_analysis_store)
        self.assertNotIn(user_job_id, execute_jobs)
        self.assertNotIn(admin_job_id, execute_jobs)
        self.assertIsNone(get_bundle(user_analysis_id))
        self.assertIsNone(get_bundle(admin_analysis_id))
        self.assertFalse(artifact_path.exists())

    def test_route_role_mapping_covers_common_gaps(self):
        self.assertEqual(_classify_role("/admin/users", "User role management"), "DASHBOARD")
        self.assertEqual(_classify_role("/account/profile", "My account"), "CHECKOUT")
        self.assertEqual(_classify_role("/signup", "Create account"), "LOGIN")


if __name__ == "__main__":
    unittest.main()
