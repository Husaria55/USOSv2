"""UserService: konta i logowanie (UC0)."""
import asyncio

from sqlalchemy import func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, Conflict
from app.models import User
from app.security import create_token, hash_password, verify_password

# Hash do porównania, gdy konta nie ma - czas odpowiedzi nie zdradza, czy e-mail istnieje.
_DUMMY_HASH = hash_password("x")


class BadCredentials(AppError):
    status = 401


async def login(session: AsyncSession, email: str, password: str) -> tuple[str, User]:
    user = (await session.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()
    # bcrypt w wątku, żeby nie blokować pętli zdarzeń na kilkadziesiąt ms
    ok = await asyncio.to_thread(verify_password, password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
        raise BadCredentials("BAD_CREDENTIALS", "Niepoprawny e-mail lub hasło.")
    return create_token(user.id, user.role), user


async def create_user(session: AsyncSession, *, email: str, password: str, full_name: str, role: str,
                      index_no: str | None = None, program_id: int | None = None, semester: int | None = None,
                      title: str | None = None, department: str | None = None) -> int:
    if role == "STUDENT" and not (index_no and program_id and semester):
        raise Conflict("STUDENT_DATA", "Student musi mieć numer indeksu, kierunek i semestr.")
    if role == "LECTURER" and not department:
        raise Conflict("LECTURER_DATA", "Prowadzący musi mieć jednostkę.")
    values = dict(email=email, password_hash=await asyncio.to_thread(hash_password, password),
                  full_name=full_name, role=role)
    if role == "STUDENT":
        values |= dict(index_no=index_no, program_id=program_id, semester=semester)
    elif role == "LECTURER":
        values |= dict(title=title, department=department)
    try:
        async with session.begin_nested():
            return (await session.execute(insert(User).values(**values).returning(User.id))).scalar_one()
    except IntegrityError as e:
        raise Conflict("DUPLICATE", "Użytkownik z tym e-mailem lub numerem indeksu już istnieje.") from e


async def search(session: AsyncSession, q: str | None, role: str | None, limit: int = 50) -> list[User]:
    query = select(User).order_by(User.full_name).limit(limit)
    if role:
        query = query.where(User.role == role)
    if q:
        like = f"%{q}%"
        query = query.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.index_no.ilike(like)))
    return list((await session.execute(query)).scalars())
