import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import LoginRequest, Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("eve.auth")


@router.post(
    "/signup",
    response_model=UserOut,
    status_code=201,
    summary="Register a new user",
)
def signup(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A user with this email already exists")

    user = User(
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("user signed up: user_id=%s", user.id)
    return user


@router.post("/login", response_model=Token, summary="Log in and obtain a JWT access token")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    # Same error for unknown email and wrong password: do not reveal which one failed.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Incorrect email or password")

    logger.info("user logged in: user_id=%s", user.id)
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut, summary="Get the authenticated user")
def me(user: User = Depends(get_current_user)):
    return user
