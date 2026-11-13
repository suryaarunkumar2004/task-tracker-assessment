from __future__ import annotations

import os
import tempfile
import unittest
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient

# Ensure test database is used
os.environ["APP_ENV"] = "testing"


class TaskTrackerTestCase(unittest.TestCase):
    db_fd: int
    db_path: str
    app_module: Any
    app: Flask
    client: FlaskClient

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.environ["DATABASE_PATH"] = self.db_path
        
        # Import app after setting test database path
        import app
        self.app_module = app
        app.DATABASE_PATH = self.db_path
        app.init_db()

        self.app = app.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def login_demo(self, account="alex"):
        return self.client.post("/auth/demo", data={"account": account}, follow_redirects=True)

    def test_unauthenticated_redirect(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_unauthenticated_api_returns_401(self):
        response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertIn("error", data)

    def test_demo_login_and_logout(self):
        resp = self.login_demo("alex")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Alex Johnson", resp.data)

        # Logout
        resp_logout = self.client.post("/logout", follow_redirects=True)
        self.assertEqual(resp_logout.status_code, 200)
        self.assertIn(b"Sign in with Google", resp_logout.data)

    def test_create_task_success(self):
        self.login_demo("alex")
        payload = {
            "title": "Setup CI/CD Pipeline",
            "description": "Configure GitHub Actions workflow for automated test execution",
            "priority": "High",
            "due_date": "2026-12-01"
        }
        res = self.client.post("/api/tasks", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn("task", data)
        task = data["task"]
        self.assertEqual(task["title"], "Setup CI/CD Pipeline")
        self.assertEqual(task["description"], payload["description"])
        self.assertEqual(task["status"], "Planned")  # Must default to Planned
        self.assertEqual(task["priority"], "High")
        self.assertEqual(task["due_date"], "2026-12-01")
        self.assertIsNotNone(task["created_at"])

    def test_create_task_validation(self):
        self.login_demo("alex")

        # Missing title
        res = self.client.post("/api/tasks", json={"title": "   "})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())

        # Title exceeding 100 characters
        res = self.client.post("/api/tasks", json={"title": "A" * 101})
        self.assertEqual(res.status_code, 400)

        # Description exceeding 500 characters
        res = self.client.post("/api/tasks", json={"title": "Valid", "description": "B" * 501})
        self.assertEqual(res.status_code, 400)

        # Invalid priority
        res = self.client.post("/api/tasks", json={"title": "Valid", "priority": "Urgent"})
        self.assertEqual(res.status_code, 400)

        # Invalid date format
        res = self.client.post("/api/tasks", json={"title": "Valid", "due_date": "12/01/2026"})
        self.assertEqual(res.status_code, 400)

    def test_user_data_isolation(self):
        # User 1 creates task
        self.login_demo("alex")
        res1 = self.client.post("/api/tasks", json={"title": "Alex Private Task"})
        task_id = res1.get_json()["task"]["id"]

        # User 2 logs in
        self.login_demo("taylor")
        res_list = self.client.get("/api/tasks")
        tasks = res_list.get_json()["tasks"]
        self.assertEqual(len(tasks), 0)  # Taylor sees NO tasks from Alex

        # Taylor tries to update Alex's task
        res_patch = self.client.patch(f"/api/tasks/{task_id}", json={"status": "In Progress"})
        self.assertEqual(res_patch.status_code, 404)

        # Taylor tries to delete Alex's task
        res_del = self.client.delete(f"/api/tasks/{task_id}")
        self.assertEqual(res_del.status_code, 404)

    def test_status_transitions(self):
        self.login_demo("alex")
        res = self.client.post("/api/tasks", json={"title": "State Transition Test"})
        task_id = res.get_json()["task"]["id"]

        # Move to In Progress
        res2 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "In Progress"})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()["task"]["status"], "In Progress")

        # Move to Complete
        res3 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "Complete"})
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.get_json()["task"]["status"], "Complete")

        # Move back to Planned
        res4 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "Planned"})
        self.assertEqual(res4.status_code, 200)
        self.assertEqual(res4.get_json()["task"]["status"], "Planned")

        # Attempt invalid status
        res5 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "Cancelled"})
        self.assertEqual(res5.status_code, 400)

    def test_soft_delete_and_restore(self):
        self.login_demo("alex")
        res = self.client.post("/api/tasks", json={"title": "Delete and Undo Test"})
        task_id = res.get_json()["task"]["id"]

        # Soft delete
        del_res = self.client.delete(f"/api/tasks/{task_id}")
        self.assertEqual(del_res.status_code, 200)

        # Verify not in active tasks
        list_res = self.client.get("/api/tasks")
        self.assertEqual(len(list_res.get_json()["tasks"]), 0)

        # Restore
        restore_res = self.client.post(f"/api/tasks/{task_id}/restore")
        self.assertEqual(restore_res.status_code, 200)

        # Verify in active tasks again
        list_res2 = self.client.get("/api/tasks")
        self.assertEqual(len(list_res2.get_json()["tasks"]), 1)
        self.assertEqual(list_res2.get_json()["tasks"][0]["id"], task_id)

    def test_clear_completed_and_restore_multiple(self):
        self.login_demo("alex")
        # 1 Planned, 2 Complete
        _ = self.client.post("/api/tasks", json={"title": "Task 1"})
        r2 = self.client.post("/api/tasks", json={"title": "Task 2"})
        r3 = self.client.post("/api/tasks", json={"title": "Task 3"})
        id2 = r2.get_json()["task"]["id"]
        id3 = r3.get_json()["task"]["id"]

        self.client.patch(f"/api/tasks/{id2}", json={"status": "Complete"})
        self.client.patch(f"/api/tasks/{id3}", json={"status": "Complete"})

        # Clear completed
        clear_res = self.client.post("/api/tasks/clear-completed")
        self.assertEqual(clear_res.status_code, 200)
        self.assertEqual(clear_res.get_json()["cleared_count"], 2)

        # Only 1 active task left
        active = self.client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["title"], "Task 1")

        # Restore multiple
        restore_res = self.client.post("/api/tasks/restore-multiple", json={"task_ids": [id2, id3]})
        self.assertEqual(restore_res.status_code, 200)
        self.assertEqual(restore_res.get_json()["restored_count"], 2)

        all_active = self.client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual(len(all_active), 3)

    def test_export_tasks(self):
        self.login_demo("alex")
        self.client.post("/api/tasks", json={"title": "Export Test Task", "priority": "High"})

        # CSV Export
        csv_res = self.client.get("/api/tasks/export?format=csv")
        self.assertEqual(csv_res.status_code, 200)
        self.assertEqual(csv_res.mimetype, "text/csv")
        self.assertIn(b"Export Test Task", csv_res.data)
        self.assertIn(b"Title,Description,Status,Priority", csv_res.data)

        # JSON Export
        json_res = self.client.get("/api/tasks/export?format=json")
        self.assertEqual(json_res.status_code, 200)
        tasks = json_res.get_json()["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Export Test Task")

    def test_signup_and_email_login(self):
        signup_data = {
            "name": "Jordan Lee",
            "email": "jordan@example.com",
            "password": "securepassword123",
            "confirm_password": "securepassword123",
            "remember_me": "on",
        }
        res = self.client.post("/auth/signup", data=signup_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Jordan Lee", res.data)

        # Verify session is authenticated and remember_me flag is active
        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get("user_id"))
            self.assertTrue(sess.permanent)

        # Log out
        self.client.post("/logout", follow_redirects=True)

        # Log back in with valid email credentials
        login_res = self.client.post(
            "/auth/login-email",
            data={
                "email": "jordan@example.com",
                "password": "securepassword123",
                "remember_me": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(login_res.status_code, 200)
        self.assertIn(b"Jordan Lee", login_res.data)

        # Attempt login with invalid password
        self.client.post("/logout", follow_redirects=True)
        bad_login = self.client.post(
            "/auth/login-email",
            data={"email": "jordan@example.com", "password": "wrongpassword"},
            follow_redirects=True,
        )
        self.assertEqual(bad_login.status_code, 200)
        self.assertIn(b"Invalid email or password", bad_login.data)

    def test_signup_validation(self):
        # Mismatched passwords
        res1 = self.client.post(
            "/auth/signup",
            data={
                "name": "Sam",
                "email": "sam@example.com",
                "password": "pass1234",
                "confirm_password": "pass5678",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Passwords do not match", res1.data)

        # Password too short (< 6 chars)
        res2 = self.client.post(
            "/auth/signup",
            data={
                "name": "Sam",
                "email": "sam@example.com",
                "password": "123",
                "confirm_password": "123",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Password must be at least 6 characters", res2.data)

        # Duplicate email
        self.client.post(
            "/auth/signup",
            data={
                "name": "Sam",
                "email": "sam@example.com",
                "password": "pass1234",
                "confirm_password": "pass1234",
            },
            follow_redirects=True,
        )
        # Log out so the subsequent signup attempt can reach the login/signup page redirect
        self.client.post("/logout", follow_redirects=True)

        dup_res = self.client.post(
            "/auth/signup",
            data={
                "name": "Sam",
                "email": "sam@example.com",
                "password": "pass1234",
                "confirm_password": "pass1234",
            },
            follow_redirects=True,
        )
        self.assertIn(b"An account with this email already exists", dup_res.data)

    def test_forgot_password_and_otp_reset(self):
        # Register user
        self.client.post(
            "/auth/signup",
            data={
                "name": "Casey Morgan",
                "email": "casey@example.com",
                "password": "originalpass123",
                "confirm_password": "originalpass123",
            },
            follow_redirects=True,
        )
        self.client.post("/logout", follow_redirects=True)

        # Request OTP for forgot password
        forgot_res = self.client.post(
            "/auth/forgot-password",
            data={"email": "casey@example.com"},
            follow_redirects=False,
        )
        self.assertEqual(forgot_res.status_code, 302)
        loc = forgot_res.headers["Location"]
        self.assertIn("tab=reset", loc)
        self.assertIn("casey@example.com", loc)
        self.assertIn("demo_otp=", loc)

        # Retrieve generated OTP from database
        with self.app.app_context():
            db = self.app_module.get_db()
            otp_row = db.execute(
                "SELECT otp_code FROM otps WHERE email = 'casey@example.com' AND used = 0 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(otp_row)
            otp_code = otp_row["otp_code"]
            self.assertEqual(len(otp_code), 6)

        # Attempt reset with wrong OTP
        bad_reset = self.client.post(
            "/auth/reset-password",
            data={
                "email": "casey@example.com",
                "otp_code": "000000",
                "new_password": "brandnewpass999",
                "confirm_password": "brandnewpass999",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Invalid or expired OTP", bad_reset.data)

        # Reset with correct OTP
        good_reset = self.client.post(
            "/auth/reset-password",
            data={
                "email": "casey@example.com",
                "otp_code": otp_code,
                "new_password": "brandnewpass999",
                "confirm_password": "brandnewpass999",
            },
            follow_redirects=True,
        )
        self.assertEqual(good_reset.status_code, 200)
        self.assertIn(b"Password reset successfully", good_reset.data)

        # Verify old password fails
        fail_login = self.client.post(
            "/auth/login-email",
            data={"email": "casey@example.com", "password": "originalpass123"},
            follow_redirects=True,
        )
        self.assertIn(b"Invalid email or password", fail_login.data)

        # Verify new password succeeds
        pass_login = self.client.post(
            "/auth/login-email",
            data={"email": "casey@example.com", "password": "brandnewpass999"},
            follow_redirects=True,
        )
        self.assertEqual(pass_login.status_code, 200)
        self.assertIn(b"Casey Morgan", pass_login.data)


if __name__ == "__main__":
    unittest.main()
