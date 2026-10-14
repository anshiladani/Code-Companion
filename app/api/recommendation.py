from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.auth import get_current_student
from app.models.schemas import CodingProblem, StudentProfile

router = APIRouter(prefix="/recommendation", tags=["Adaptive Engine"])


@router.get("/next-problem/{student_id}")
def get_recommended_problem(
    student_id: int,
    db: Session = Depends(get_db),
    current_student: StudentProfile = Depends(get_current_student),
):
    student = db.query(StudentProfile).filter(StudentProfile.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    if student.id != current_student.id:
        raise HTTPException(status_code=403, detail="You can only view recommendations for your own profile.")
    problem = (
        db.query(CodingProblem)
        .order_by(
            (CodingProblem.difficulty_rating - student.skill_rating) * (CodingProblem.difficulty_rating - student.skill_rating),
            CodingProblem.id,
        )
        .first()
    )
    if not problem:
        raise HTTPException(status_code=404, detail="No coding problems are available yet.")
    return {
        "student_username": student.username,
        "student_rating": student.skill_rating,
        "problem_id": problem.id,
        "title": problem.title,
        "description": problem.description,
        "concept": problem.concept,
        "difficulty": problem.difficulty_rating,
    }
