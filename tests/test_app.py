import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.assistant import AssistantRequest, request_tutor_hint
from app.api.auth import LoginRequest, login_or_register_user
from app.api.execution import ExecutionRequest, run_code
from app.api.recommendation import get_recommended_problem
from app.db.database import Base
from app.main import DEFAULT_PROBLEMS, app, health_check, lifespan
from app.models.schemas import CodingProblem, LoginHistory, StudentProfile, UserSession
from app.sandbox.executor import execute_python_code


class RequestValidationTests(unittest.TestCase):
    def test_username_is_trimmed_and_case_normalized(self):
        self.assertEqual(LoginRequest(username="  Alex_Dev  ").username, "alex_dev")

    def test_invalid_username_is_rejected(self):
        for username in ("ab", "bad name", "<script>"):
            with self.subTest(username=username), self.assertRaises(ValidationError):
                LoginRequest(username=username)

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

        result = get_recommended_problem(5, db)
        self.assertEqual(result["title"], "Count Vowels")
        self.assertEqual(result["student_username"], "alex")

    def test_missing_student_is_a_not_found_error(self):
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db = MagicMock()
        db.query.return_value = query

        with self.assertRaises(HTTPException) as error:
            get_recommended_problem(99, db)
        self.assertEqual(error.exception.status_code, 404)


class LoginTests(unittest.TestCase):
    def test_profile_reuse_records_logins_without_duplicate_sessions(self):
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=test_engine)
        test_sessions = sessionmaker(bind=test_engine)

        with test_sessions() as db:
            first = login_or_register_user(LoginRequest(username="Student_One"), db)
            second = login_or_register_user(LoginRequest(username="student_one"), db)
            self.assertEqual(first["student_id"], second["student_id"])
            self.assertEqual(first["username"], "student_one")
            self.assertEqual(db.query(LoginHistory).count(), 2)
            self.assertEqual(db.query(UserSession).count(), 1)
            legacy_profile = StudentProfile(username="Legacy_User")
            db.add(legacy_profile)
            db.commit()
            reused = login_or_register_user(LoginRequest(username="legacy_user"), db)
            self.assertEqual(reused["student_id"], legacy_profile.id)
            self.assertEqual(db.query(StudentProfile).count(), 2)

        test_engine.dispose()


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


class RouteTests(unittest.TestCase):
    def test_public_api_routes_are_registered(self):
        paths = app.openapi()["paths"]
        self.assertIn("/auth/login", paths)
        self.assertIn("/execution/run", paths)
        self.assertIn("/recommendation/next-problem/{student_id}", paths)
        self.assertIn("/assistant/get-hint", paths)
        self.assertIn("/health", paths)
        self.assertNotIn("/auth/recent-logins", paths)


if __name__ == "__main__":
    unittest.main()
