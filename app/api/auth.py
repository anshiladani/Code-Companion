import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.schemas import AuthToken, LoginHistory, StudentProfile, SubmissionLog, UserSession

router = APIRouter(prefix="/auth", tags=["Profile Management"])
PASSWORD_ITERATIONS = 310_000


class Credentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class RegistrationRequest(Credentials):
    display_name: str = Field(min_length=1, max_length=80)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=80)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if stored_hash is None:
        return False
    try:
        iterations_text, salt_hex, digest_hex = stored_hash.split("$")
        iterations = int(iterations_text)
        if iterations < 1 or iterations > 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def issue_token(db: Session, student: StudentProfile) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(student_id=student.id, token_hash=hashlib.sha256(token.encode("ascii")).hexdigest()))
    db.add(LoginHistory(student_id=student.id))
    session = db.query(UserSession).filter(UserSession.student_id == student.id).first()
    if session is None:
        db.add(UserSession(student_id=student.id))
    else:
        session.last_active = datetime.now(timezone.utc)
    return token


def profile_response(student: StudentProfile) -> dict:
    return {
        "student_id": student.id,
        "username": student.username,
        "display_name": student.display_name or student.username,
        "skill_rating": student.skill_rating,
        "created_at": student.created_at,
    }


def get_current_student(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> StudentProfile:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to manage your profile.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    auth_token = db.query(AuthToken).filter(AuthToken.token_hash == token_hash).first()
    if auth_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session is invalid. Please sign in again.")
    student = db.query(StudentProfile).filter(StudentProfile.id == auth_token.student_id).first()
    if student is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your profile is no longer available.")
    return student


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, db: Session = Depends(get_db)):
    username_filter = func.lower(StudentProfile.username) == payload.username
    student = db.query(StudentProfile).filter(username_filter).first()
    if student:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username is already registered.")
    student = StudentProfile(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    db.add(student)
    try:
        db.flush()
        token = issue_token(db, student)
        db.commit()
        db.refresh(student)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username is already registered.") from error
    return {"access_token": token, "token_type": "bearer", "profile": profile_response(student)}


@router.post("/login")
def login_or_register_user(payload: Credentials, db: Session = Depends(get_db)):
    username_filter = func.lower(StudentProfile.username) == payload.username
    student = db.query(StudentProfile).filter(username_filter).first()
    if student is None or not verify_password(payload.password, student.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password.")
    token = issue_token(db, student)
    try:
        db.commit()
        db.refresh(student)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to record this login. Please try again.") from error
    return {"access_token": token, "token_type": "bearer", "profile": profile_response(student)}


@router.get("/me")
def get_profile(student: StudentProfile = Depends(get_current_student)):
    return profile_response(student)


@router.patch("/me")
def update_profile(
    payload: ProfileUpdate,
    student: StudentProfile = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    student.display_name = payload.display_name
    db.commit()
    db.refresh(student)
    return profile_response(student)


@router.get("/me/login-history")
def get_login_history(
    student: StudentProfile = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(LoginHistory)
        .filter(LoginHistory.student_id == student.id)
        .order_by(LoginHistory.login_time.desc())
        .limit(10)
        .all()
    )
    return [{"login_time": row.login_time} for row in rows]


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    student: StudentProfile = Depends(get_current_student),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _, _, token = (authorization or "").partition(" ")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    db.query(AuthToken).filter(
        AuthToken.student_id == student.id,
        AuthToken.token_hash == token_hash,
    ).delete(synchronize_session=False)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    student: StudentProfile = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    db.query(AuthToken).filter(AuthToken.student_id == student.id).delete(synchronize_session=False)
    db.query(LoginHistory).filter(LoginHistory.student_id == student.id).delete(synchronize_session=False)
    db.query(UserSession).filter(UserSession.student_id == student.id).delete(synchronize_session=False)
    db.query(SubmissionLog).filter(SubmissionLog.student_id == student.id).delete(synchronize_session=False)
    db.delete(student)
    db.commit()
