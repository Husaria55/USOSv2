from fastapi import APIRouter, Depends

from app.api.deps import session
from app.api.schemas import Login
from app.services import queries, users

router = APIRouter(prefix="/api/auth")


@router.post("/login")
async def login(body: Login, db=Depends(session)):
    """UC0. Token JWT ważny kilka godzin: studenci logują się przed turą, nie w jej pierwszej sekundzie."""
    token, user = await users.login(db, body.email, body.password)
    return {"token": token, "user": queries.user_dict(user)}
