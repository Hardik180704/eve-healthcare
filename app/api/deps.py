from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AuthenticationError
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the JWT bearer token."""
    if credentials is None:
        raise AuthenticationError("Not authenticated")
    subject = decode_access_token(credentials.credentials)
    if subject is None:
        raise AuthenticationError("Invalid or expired token")
    try:
        user_id = UUID(subject)
    except ValueError:
        raise AuthenticationError("Invalid or expired token") from None
    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Invalid or expired token")
    return user
