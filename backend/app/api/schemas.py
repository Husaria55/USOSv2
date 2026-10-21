from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["LECTURE", "EXERCISE", "LAB", "SEMINAR"]
Parity = Literal["ALL", "ODD", "EVEN"]


class Login(BaseModel):
    email: str
    password: str


class SectionRef(BaseModel):
    section_id: int


class AdminEnroll(BaseModel):
    student_id: int
    section_id: int


class NewProgram(BaseModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)


class NewTerm(BaseModel):
    code: str = Field(max_length=10)
    starts_on: date
    ends_on: date


class NewRoom(BaseModel):
    building: str = Field(max_length=20)
    number: str = Field(max_length=20)
    seats: int = Field(gt=0, le=32000)


class NewCourse(BaseModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)
    ects: int = Field(gt=0, le=60)
    description: str | None = None


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    ects: int | None = Field(default=None, gt=0, le=60)
    description: str | None = None


class Prerequisite(BaseModel):
    required_course_id: int


class NewSection(BaseModel):
    course_id: int
    term_id: int
    code: str = Field(max_length=10)
    kind: Kind
    capacity: int = Field(gt=0, le=32000)
    waitlist_limit: int = Field(default=50, ge=0, le=32000)


class SectionLimits(BaseModel):
    capacity: int | None = Field(default=None, gt=0, le=32000)
    waitlist_limit: int | None = Field(default=None, ge=0, le=32000)


class NewMeeting(BaseModel):
    weekday: int = Field(ge=1, le=7)
    start: time
    end: time
    parity: Parity = "ALL"
    room_id: int | None = None


class LecturerRef(BaseModel):
    lecturer_id: int


class NewRound(BaseModel):
    term_id: int
    name: str = Field(max_length=50)
    opens_at: datetime
    closes_at: datetime
    program_ids: list[int] = []


class RoundUpdate(BaseModel):
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    program_ids: list[int] | None = None


class NewUser(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=6)
    full_name: str = Field(max_length=200)
    role: Literal["STUDENT", "LECTURER", "ADMIN"]
    index_no: str | None = Field(default=None, max_length=10)
    program_id: int | None = None
    semester: int | None = Field(default=None, ge=1, le=12)
    title: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=100)


class GradesImport(BaseModel):
    csv: str
