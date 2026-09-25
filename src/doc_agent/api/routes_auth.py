"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from doc_agent.auth import (
    create_access_token,
    get_current_user,
    verify_password,
)
from doc_agent.db.session import get_session
from doc_agent.db.models import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    """Authenticate user and return JWT token."""
    with get_session() as session:
        user = session.query(User).filter(User.username == req.username).first()
        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        token = create_access_token(
            data={"sub": user.username, "role": user.role}
        )
        return TokenResponse(
            access_token=token,
            role=user.role,
        )


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    """Get current user info."""
    return {"username": user["username"], "role": user["role"]}
