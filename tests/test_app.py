import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.assistant import AssistantRequest, request_tutor_hint
from app.api.auth import (
    Credentials,
    ProfileUpdate,
    RegistrationRequest,
    delete_profile,
    get_current_student,
    get_profile,
    hash_password,
    login_or_register_user,
    register,
    update_profile,
    verify_password,
)
from app.api.execution import ExecutionRequest, run_code
from app.api.recommendation import get_recommended_problem
from app.db.database import Base, get_db
from app.main import DEFAULT_PROBLEMS, app, health_check, lifespan
from app.models.schemas import AuthToken, CodingProblem, LoginHistory, StudentProfile, UserSession
from app.sandbox.executor import execute_python_code


class RequestValidationTests(unittest.TestCase):
    def test_username_is_trimmed_and_case_normalized(self):
        request = Credentials(username="  Alex_Dev  ", password="correct horse")
        self.assertEqual(request.username, "alex_dev")

    def test_invalid_username_is_rejected(self):
        for username in ("ab", "bad name", "<script>"):
            with self.subTest(username=username), self.assertRaises(ValidationError):
                Credentials(username=username, password="correct horse")

    def test_short_password_is_rejected(self):
        with self.assertRaises(ValidationError):
            Credentials(username="student", password="short")

    def test_execution_request_rejects_unsupported_language(self):
        with self.assertRaises(ValidationError):
            ExecutionRequest(code="print('hello')", language="javascript")

    def test_assistant_input_has_size_limits(self):
        with self.assertRaises(ValidationError):
            AssistantRequest(problem_description="x" * 5_001, student_code="")


class AssistantTests(unittest.TestCase):
    def test_hint_returns_first_choice_content(self):
        payload = AssistantRequest(problem_description="Reverse a string", student_code="print('hi')")
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Try using a loop."))]
        )
        with patch("app.api.assistant.settings.LLM_API_KEY", "test-key"), patch(
            "app.api.assistant.OpenAI", return_value=client
        ):
            self.assertEqual(request_tutor_hint(payload), {"hint": "Try using a loop."})

    def test_hint_fails_clearly_when_not_configured(self):
        payload = AssistantRequest(problem_description="Reverse a string", student_code="")
        with patch("app.api.assistant.settings.LLM_API_KEY", None):
            with self.assertRaises(HTTPException) as error:
                request_tutor_hint(payload)
        self.assertEqual(error.exception.status_code, 503)


class ExecutionTests(unittest.TestCase):
    def test_execution_is_disabled_by_default(self):
        payload = ExecutionRequest(code="print('hello')", language="python")
        with patch("app.api.execution.settings.ENABLE_LOCAL_CODE_EXECUTION", False):
            with self.assertRaises(HTTPException) as error:
                run_code(payload)
        self.assertEqual(error.exception.status_code, 503)

    def test_runner_captures_output(self):
        result = execute_python_code("print('hello')", timeout_seconds=2)
        self.assertEqual(result, {"success": True, "stdout": "hello\n", "stderr": ""})

    def test_runner_reports_runtime_errors_and_limits_output(self):
        result = execute_python_code("raise ValueError('bad input')", timeout_seconds=2)
        self.assertFalse(result["success"])
        self.assertIn("ValueError: bad input", result["stderr"])

        result = execute_python_code("print('x' * 20000)", timeout_seconds=2)
        self.assertIn("[Output truncated]", result["stdout"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 16_500)

    def test_runner_stops_code_that_exceeds_timeout(self):
        result = execute_python_code("while True: pass", timeout_seconds=0.1)
        self.assertFalse(result["success"])
        self.assertIn("timed out", result["stderr"])


class RecommendationTests(unittest.TestCase):
    def test_recommendation_returns_nearest_problem(self):
        student = SimpleNamespace(id=5, username="alex", skill_rating=90)
        problem = SimpleNamespace(
            id=3,
            title="Count Vowels",
            description="Count vowels in text.",
            concept="Strings",
            difficulty_rating=90,
        )
        student_query = MagicMock()
        student_query.filter.return_value.first.return_value = student
        problem_query = MagicMock()
        problem_query.order_by.return_value.first.return_value = problem
        db = MagicMock()
        db.query.side_effect = [student_query, problem_query]

        result = get_recommended_problem(5, db, student)
        self.assertEqual(result["title"], "Count Vowels")
        self.assertEqual(result["student_username"], "alex")

    def test_missing_student_is_a_not_found_error(self):
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db = MagicMock()
        db.query.return_value = query

        with self.assertRaises(HTTPException) as error:
            get_recommended_problem(99, db, SimpleNamespace(id=99))
        self.assertEqual(error.exception.status_code, 404)


class LoginTests(unittest.TestCase):
    def setUp(self):
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=test_engine)
        self.test_engine = test_engine
        self.test_sessions = sessionmaker(bind=test_engine)

    def tearDown(self):
        self.test_engine.dispose()

    def test_registration_login_and_password_hashing(self):
        with self.test_sessions() as db:
            first = register(
                RegistrationRequest(username="Student_One", display_name="Student One", password="correct horse"),
                db,
            )
            stored_profile = db.query(StudentProfile).first()
            self.assertNotEqual(stored_profile.password_hash, "correct horse")
            self.assertTrue(verify_password("correct horse", stored_profile.password_hash))
            self.assertFalse(verify_password("wrong password", stored_profile.password_hash))
            second = login_or_register_user(
                Credentials(username="STUDENT_ONE", password="correct horse"),
                db,
            )
            self.assertEqual(first["profile"]["student_id"], second["profile"]["student_id"])
            self.assertNotEqual(first["access_token"], second["access_token"])
            self.assertEqual(db.query(LoginHistory).count(), 2)
            self.assertEqual(db.query(UserSession).count(), 1)

    def test_existing_demo_profile_cannot_be_claimed_without_password(self):
        with self.test_sessions() as db:
            legacy_profile = StudentProfile(username="Legacy_User")
            db.add(legacy_profile)
            db.commit()
            with self.assertRaises(HTTPException) as error:
                register(
                    RegistrationRequest(username="LEGACY_USER", display_name="Another", password="some password"),
                    db,
                )
            self.assertEqual(error.exception.status_code, 409)

    def test_invalid_login_does_not_create_a_profile(self):
        with self.test_sessions() as db:
            with self.assertRaises(HTTPException) as error:
                login_or_register_user(Credentials(username="new_student", password="correct horse"), db)
            self.assertEqual(error.exception.status_code, 401)
            self.assertEqual(db.query(StudentProfile).count(), 0)

    def test_bearer_token_scopes_profile_update_to_its_owner(self):
        with self.test_sessions() as db:
            result = register(
                RegistrationRequest(username="student_one", display_name="Student One", password="correct horse"),
                db,
            )
            student = get_current_student(f"Bearer {result['access_token']}", db)
            updated = update_profile(ProfileUpdate(display_name="Updated Name"), student, db)
            self.assertEqual(updated["display_name"], "Updated Name")
            self.assertEqual(get_profile(student)["username"], "student_one")
            with self.assertRaises(HTTPException) as error:
                get_current_student("Bearer invalid-token", db)
            self.assertEqual(error.exception.status_code, 401)

    def test_profile_deletion_removes_login_history_and_revokes_tokens(self):
        with self.test_sessions() as db:
            result = register(
                RegistrationRequest(username="student_one", display_name="Student One", password="correct horse"),
                db,
            )
            student = get_current_student(f"Bearer {result['access_token']}", db)
            delete_profile(student, db)
            self.assertEqual(db.query(StudentProfile).count(), 0)
            self.assertEqual(db.query(LoginHistory).count(), 0)
            self.assertEqual(db.query(AuthToken).count(), 0)


class StartupTests(unittest.TestCase):
    def test_default_problems_are_seeded_idempotently(self):
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        test_sessions = sessionmaker(bind=test_engine)

        async def start_app():
            async with lifespan(app):
                pass

        with patch("app.main.engine", test_engine), patch("app.main.SessionLocal", test_sessions):
            asyncio.run(start_app())
            with test_sessions() as db:
                self.assertEqual(db.query(CodingProblem).count(), len(DEFAULT_PROBLEMS))
                self.assertEqual(health_check(db), {"status": "ok"})
            asyncio.run(start_app())
            with test_sessions() as db:
                self.assertEqual(db.query(CodingProblem).count(), len(DEFAULT_PROBLEMS))
        test_engine.dispose()

    def test_existing_profile_table_is_upgraded_without_losing_rows(self):
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with test_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE student_profiles (id INTEGER PRIMARY KEY, username VARCHAR(30) NOT NULL UNIQUE, "
                "skill_rating FLOAT NOT NULL DEFAULT 100, created_at DATETIME NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO student_profiles (username, skill_rating, created_at) "
                "VALUES ('existing_student', 100, CURRENT_TIMESTAMP)"
            )
        test_sessions = sessionmaker(bind=test_engine)

        async def start_app():
            async with lifespan(app):
                pass

        with patch("app.main.engine", test_engine), patch("app.main.SessionLocal", test_sessions):
            asyncio.run(start_app())
        with test_sessions() as db:
            profile = db.query(StudentProfile).filter_by(username="existing_student").one()
            self.assertEqual(profile.display_name, None)
            self.assertEqual(profile.password_hash, None)
        test_engine.dispose()


class RouteTests(unittest.TestCase):
    def test_public_api_routes_are_registered(self):
        paths = app.openapi()["paths"]
        self.assertIn("/auth/login", paths)
        self.assertIn("/auth/register", paths)
        self.assertIn("/auth/me", paths)
        self.assertIn("/auth/me/login-history", paths)
        self.assertIn("/auth/logout", paths)
        self.assertIn("/execution/run", paths)
        self.assertIn("/recommendation/next-problem/{student_id}", paths)
        self.assertIn("/assistant/get-hint", paths)
        self.assertIn("/health", paths)
        self.assertNotIn("/auth/recent-logins", paths)

    def test_profile_lifecycle_through_http_api(self):
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        test_sessions = sessionmaker(bind=test_engine)

        def override_get_db():
            with test_sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with patch("app.main.engine", test_engine), patch("app.main.SessionLocal", test_sessions):
                with TestClient(app) as client:
                    created = client.post(
                        "/auth/register",
                        json={
                            "username": "student_one",
                            "display_name": "Student One",
                            "password": "correct horse",
                        },
                    )
                    self.assertEqual(created.status_code, 201)
                    token = created.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    self.assertEqual(client.get("/auth/me", headers=headers).status_code, 200)
                    self.assertEqual(client.get("/auth/me/login-history", headers=headers).status_code, 200)

                    updated = client.patch(
                        "/auth/me",
                        headers=headers,
                        json={"display_name": "Updated Name"},
                    )
                    self.assertEqual(updated.status_code, 200)
                    self.assertEqual(updated.json()["display_name"], "Updated Name")
                    self.assertEqual(
                        client.get(
                            f"/recommendation/next-problem/{created.json()['profile']['student_id']}",
                            headers=headers,
                        ).status_code,
                        200,
                    )
                    another_profile = client.post(
                        "/auth/register",
                        json={
                            "username": "student_two",
                            "display_name": "Student Two",
                            "password": "correct horse",
                        },
                    )
                    self.assertEqual(another_profile.status_code, 201)
                    self.assertEqual(
                        client.get(
                            f"/recommendation/next-problem/{another_profile.json()['profile']['student_id']}",
                            headers=headers,
                        ).status_code,
                        403,
                    )

                    self.assertEqual(client.post("/auth/logout", headers=headers).status_code, 204)
                    self.assertEqual(client.get("/auth/me", headers=headers).status_code, 401)

                    signed_in = client.post(
                        "/auth/login",
                        json={"username": "student_one", "password": "correct horse"},
                    )
                    self.assertEqual(signed_in.status_code, 200)
                    delete_headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
                    self.assertEqual(client.delete("/auth/me", headers=delete_headers).status_code, 204)
                    self.assertEqual(client.get("/auth/me", headers=delete_headers).status_code, 401)
        finally:
            app.dependency_overrides.pop(get_db, None)
            test_engine.dispose()


if __name__ == "__main__":
    unittest.main()
