from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(30), unique=True, index=True, nullable=False)
    display_name = Column(String(80), nullable=True)
    password_hash = Column(String(256), nullable=True)
    skill_rating = Column(Float, default=100.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class LoginHistory(Base):
    __tablename__ = "login_history"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False)
    login_time = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id", ondelete="CASCADE"), unique=True, nullable=False)
    last_active = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

class CodingProblem(Base):
    __tablename__ = "coding_problems"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    concept = Column(String(50), nullable=False)
    difficulty_rating = Column(Float, nullable=False, index=True)

class SubmissionLog(Base):
    __tablename__ = "submission_logs"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("coding_problems.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False)
