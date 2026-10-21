"""Mapowanie tabel (struktura w migrations/versions/0001_initial.sql).

Ograniczenia (CHECK, UNIQUE, indeksy częściowe) są zdefiniowane w migracji,
tu tylko kolumny potrzebne do zapytań.
"""
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import BigInteger, Computed, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class Program(Base):
    __tablename__ = "program"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    index_no: Mapped[str | None] = mapped_column(String(10))
    program_id: Mapped[int | None] = mapped_column(ForeignKey("program.id"))
    semester: Mapped[int | None] = mapped_column(SmallInteger)
    title: Mapped[str | None] = mapped_column(String(50))
    department: Mapped[str | None] = mapped_column(String(100))


class Course(Base):
    __tablename__ = "course"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    ects: Mapped[int] = mapped_column(SmallInteger)
    description: Mapped[str | None] = mapped_column(Text)


class CoursePrerequisite(Base):
    __tablename__ = "course_prerequisite"
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), primary_key=True)
    required_course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), primary_key=True)


class Term(Base):
    __tablename__ = "term"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(10))
    starts_on: Mapped[date]
    ends_on: Mapped[date]


class EnrollmentRound(Base):
    __tablename__ = "enrollment_round"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id"))
    name: Mapped[str] = mapped_column(String(50))
    opens_at: Mapped[datetime]
    closes_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(16), server_default="PLANNED")


class RoundProgram(Base):
    __tablename__ = "round_program"
    round_id: Mapped[int] = mapped_column(ForeignKey("enrollment_round.id"), primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"), primary_key=True)


class Room(Base):
    __tablename__ = "room"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    building: Mapped[str] = mapped_column(String(20))
    number: Mapped[str] = mapped_column(String(20))
    seats: Mapped[int] = mapped_column(SmallInteger)


class Section(Base):
    __tablename__ = "section"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"))
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id"))
    code: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(16))
    capacity: Mapped[int] = mapped_column(SmallInteger)
    enrolled_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    waitlist_limit: Mapped[int] = mapped_column(SmallInteger, server_default="50")


class SectionLecturer(Base):
    __tablename__ = "section_lecturer"
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), primary_key=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), primary_key=True)


class Meeting(Base):
    __tablename__ = "meeting"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time]
    end_time: Mapped[time]
    week_parity: Mapped[str] = mapped_column(String(4), server_default="ALL")


class CompletedCourse(Base):
    __tablename__ = "completed_course"
    student_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id"), primary_key=True)
    grade: Mapped[Decimal]
    passed: Mapped[bool] = mapped_column(Computed("grade >= 3.0"))


class Enrollment(Base):
    __tablename__ = "enrollment"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    enrolled_at: Mapped[datetime] = mapped_column(server_default="now()")
    dropped_at: Mapped[datetime | None]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    dropped_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entry"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    status: Mapped[str] = mapped_column(String(16), server_default="WAITING")
    created_at: Mapped[datetime] = mapped_column(server_default="clock_timestamp()")
    resolved_at: Mapped[datetime | None]
    skip_reason: Mapped[str | None] = mapped_column(String(255))
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("enrollment.id"))


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    sent_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
