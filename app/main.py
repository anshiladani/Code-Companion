from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import assistant, auth, execution, recommendation
from app.core.config import get_cors_origins
from app.db.database import Base, SessionLocal, engine, get_db
from app.models.schemas import CodingProblem


DEFAULT_PROBLEMS = (
    {
        "title": "Two Sum",
        "description": "Given a list of integers and a target, return the indices of two values that add up to the target.",
        "concept": "Arrays and hash maps",
        "difficulty_rating": 80,
    },
    {
        "title": "Count Vowels",
        "description": "Write a function that counts the vowels in a string. Treat uppercase and lowercase letters equally.",
        "concept": "Strings and loops",
        "difficulty_rating": 90,
    },
    {
        "title": "Balanced Brackets",
        "description": "Determine whether every opening bracket in a string is closed in the correct order.",
        "concept": "Stacks",
        "difficulty_rating": 100,
    },
    {
        "title": "Merge Sorted Lists",
        "description": "Combine two sorted integer lists into one sorted list without using a sorting function.",
        "concept": "Arrays and two pointers",
        "difficulty_rating": 110,
    },
    {
        "title": "First Non-Repeating Character",
        "description": "Return the first character in a string that appears exactly once, or an empty string if none exists.",
        "concept": "Strings and hash maps",
        "difficulty_rating": 120,
    },
    {
        "title": "Binary Search",
        "description": "Return the index of a target value in a sorted list using binary search, or -1 when it is absent.",
        "concept": "Searching and complexity",
        "difficulty_rating": 130,
    },
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        existing_titles = {
            title for (title,) in db.query(CodingProblem.title).all()
        }
        new_problems = [
            CodingProblem(**problem)
            for problem in DEFAULT_PROBLEMS
            if problem["title"] not in existing_titles
        ]
        if new_problems:
            db.add_all(new_problems)
            db.commit()
    yield


app = FastAPI(title="Code Companion", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Content-Type"],
)

app.include_router(auth.router)
app.include_router(execution.router)
app.include_router(recommendation.router)
app.include_router(assistant.router)


@app.get("/health", tags=["Operations"])
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/")
def read_index():
    return FileResponse(Path(__file__).resolve().parent.parent / "index.html")
