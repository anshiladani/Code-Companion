from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.schemas import StudentProfile, LoginHistory, UserSession

router = APIRouter(prefix="/auth", tags=["User Authentication & Logs"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


@router.post("/login")
def login_or_register_user(payload: LoginRequest, db: Session = Depends(get_db)):
    username_filter = func.lower(StudentProfile.username) == payload.username
    student = db.query(StudentProfile).filter(username_filter).first()
    if not student:
        student = StudentProfile(username=payload.username)
        db.add(student)
        try:
            db.commit()
            db.refresh(student)
        except IntegrityError:
            db.rollback()
            student = db.query(StudentProfile).filter(username_filter).first()
            if not student:
                raise HTTPException(status_code=409, detail="Unable to create this profile. Please try again.")

    new_log = LoginHistory(student_id=student.id)
    db.add(new_log)

    session = db.query(UserSession).filter(UserSession.student_id == student.id).first()
    if not session:
        session = UserSession(student_id=student.id)
        db.add(session)
    else:
        session.last_active = datetime.now(timezone.utc)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to record this login. Please try again.") from error
    return {
        "message": f"Welcome back, {student.username}!",
        "student_id": student.id,
        "username": student.username,
    }
