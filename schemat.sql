-- System zapisów na zajęcia: schemat bazy danych (PostgreSQL 16)

CREATE TABLE app_user (
    id            BIGSERIAL    PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name     VARCHAR(200) NOT NULL,
    role          VARCHAR(16)  NOT NULL CHECK (role IN ('STUDENT', 'LECTURER', 'ADMIN')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE student (
    user_id  BIGINT       PRIMARY KEY REFERENCES app_user(id),
    index_no VARCHAR(10)  NOT NULL UNIQUE,
    program  VARCHAR(100) NOT NULL,
    semester SMALLINT     NOT NULL CHECK (semester BETWEEN 1 AND 12)
);

CREATE TABLE lecturer (
    user_id    BIGINT       PRIMARY KEY REFERENCES app_user(id),
    title      VARCHAR(50),
    department VARCHAR(100) NOT NULL
);

-- Katalog --------------------------------------------------------------------

CREATE TABLE course (
    id          BIGSERIAL    PRIMARY KEY,
    code        VARCHAR(20)  NOT NULL UNIQUE,
    name        VARCHAR(200) NOT NULL,
    ects        SMALLINT     NOT NULL CHECK (ects > 0),
    description TEXT
);

CREATE TABLE course_prerequisite (
    course_id          BIGINT NOT NULL REFERENCES course(id) ON DELETE CASCADE,
    required_course_id BIGINT NOT NULL REFERENCES course(id),
    PRIMARY KEY (course_id, required_course_id),
    CHECK (course_id <> required_course_id)
);

CREATE TABLE term (
    id                   BIGSERIAL   PRIMARY KEY,
    code                 VARCHAR(10) NOT NULL UNIQUE,      -- np. 2026Z
    starts_on            DATE        NOT NULL,
    ends_on              DATE        NOT NULL,
    enrollment_opens_at  TIMESTAMPTZ NOT NULL,
    enrollment_closes_at TIMESTAMPTZ NOT NULL,
    status               VARCHAR(16) NOT NULL DEFAULT 'PLANNED'
                         CHECK (status IN ('PLANNED', 'OPEN', 'CLOSED')),
    CHECK (starts_on < ends_on),
    CHECK (enrollment_opens_at < enrollment_closes_at)
);

CREATE TABLE room (
    id       BIGSERIAL   PRIMARY KEY,
    building VARCHAR(20) NOT NULL,
    number   VARCHAR(20) NOT NULL,
    seats    SMALLINT    NOT NULL CHECK (seats > 0),
    UNIQUE (building, number)
);

-- Grupa zajęciowa (sekcja). Różne rozmiary grup: limit ustalany per grupa.
CREATE TABLE section (
    id             BIGSERIAL   PRIMARY KEY,
    course_id      BIGINT      NOT NULL REFERENCES course(id),
    term_id        BIGINT      NOT NULL REFERENCES term(id),
    code           VARCHAR(10) NOT NULL,                   -- np. W01, C03, L12
    kind           VARCHAR(16) NOT NULL CHECK (kind IN ('LECTURE', 'EXERCISE', 'LAB', 'SEMINAR')),
    capacity       SMALLINT    NOT NULL CHECK (capacity > 0),
    enrolled_count SMALLINT    NOT NULL DEFAULT 0 CHECK (enrolled_count >= 0),
    waitlist_limit SMALLINT    NOT NULL DEFAULT 50 CHECK (waitlist_limit >= 0),
    version        BIGINT      NOT NULL DEFAULT 0,
    UNIQUE (course_id, term_id, code),
    -- ostatnia linia obrony przed overbookingiem
    CHECK (enrolled_count <= capacity)
);

CREATE TABLE section_lecturer (
    section_id  BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    lecturer_id BIGINT NOT NULL REFERENCES lecturer(user_id),
    PRIMARY KEY (section_id, lecturer_id)
);

-- Harmonogram: cotygodniowe terminy grupy (grupa może mieć kilka terminów).
CREATE TABLE meeting (
    id          BIGSERIAL  PRIMARY KEY,
    section_id  BIGINT     NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    room_id     BIGINT     REFERENCES room(id),
    weekday     SMALLINT   NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    start_time  TIME       NOT NULL,
    end_time    TIME       NOT NULL,
    week_parity VARCHAR(4) NOT NULL DEFAULT 'ALL' CHECK (week_parity IN ('ALL', 'ODD', 'EVEN')),
    CHECK (start_time < end_time)
);
CREATE INDEX meeting_section ON meeting (section_id);
CREATE INDEX meeting_room    ON meeting (room_id, weekday);

-- Historia studiów -----------------------------------------------------------

CREATE TABLE completed_course (
    student_id BIGINT       NOT NULL REFERENCES student(user_id),
    course_id  BIGINT       NOT NULL REFERENCES course(id),
    term_id    BIGINT       NOT NULL REFERENCES term(id),
    grade      NUMERIC(2,1) NOT NULL CHECK (grade BETWEEN 2.0 AND 5.0),
    passed     BOOLEAN      NOT NULL,
    PRIMARY KEY (student_id, course_id, term_id)
);

-- Zapisy ---------------------------------------------------------------------

CREATE TABLE enrollment (
    id          BIGSERIAL   PRIMARY KEY,
    student_id  BIGINT      NOT NULL REFERENCES student(user_id),
    section_id  BIGINT      NOT NULL REFERENCES section(id),
    status      VARCHAR(16) NOT NULL CHECK (status IN ('ENROLLED', 'DROPPED')),
    source      VARCHAR(16) NOT NULL CHECK (source IN ('DIRECT', 'WAITLIST', 'ADMIN')),
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dropped_at  TIMESTAMPTZ,
    CHECK ((status = 'DROPPED') = (dropped_at IS NOT NULL))
);
-- Historia wypisów zostaje, ale aktywny zapis do grupy może być tylko jeden.
CREATE UNIQUE INDEX enrollment_one_active
    ON enrollment (student_id, section_id) WHERE status = 'ENROLLED';
CREATE INDEX enrollment_student ON enrollment (student_id) WHERE status = 'ENROLLED';

CREATE TABLE waitlist_entry (
    id            BIGSERIAL    PRIMARY KEY,
    student_id    BIGINT       NOT NULL REFERENCES student(user_id),
    section_id    BIGINT       NOT NULL REFERENCES section(id),
    status        VARCHAR(16)  NOT NULL DEFAULT 'WAITING'
                  CHECK (status IN ('WAITING', 'PROMOTED', 'SKIPPED', 'CANCELLED')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),     -- kolejność: created_at, id
    resolved_at   TIMESTAMPTZ,
    skip_reason   VARCHAR(255),
    enrollment_id BIGINT       UNIQUE REFERENCES enrollment(id),
    CHECK ((status = 'PROMOTED') = (enrollment_id IS NOT NULL)),
    CHECK ((status = 'SKIPPED') = (skip_reason IS NOT NULL))
);
CREATE UNIQUE INDEX waitlist_one_waiting
    ON waitlist_entry (student_id, section_id) WHERE status = 'WAITING';
CREATE INDEX waitlist_queue
    ON waitlist_entry (section_id, created_at, id) WHERE status = 'WAITING';

-- Outbox powiadomień: zapis w tej samej transakcji co zmiana, wysyłka przez worker.
CREATE TABLE notification (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES app_user(id),
    type       VARCHAR(32) NOT NULL,
    payload    JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at    TIMESTAMPTZ
);
CREATE INDEX notification_unsent ON notification (created_at) WHERE sent_at IS NULL;

-- Wykrywanie kolizji ---------------------------------------------------------
-- Grupy z planu studenta, których terminy nachodzą na terminy grupy :section.
-- Terminy kolidują, gdy: ten sam dzień, przecinające się godziny
-- (start1 < end2 AND start2 < end1) i pokrywające się tygodnie.
CREATE FUNCTION schedule_conflicts(p_student BIGINT, p_section BIGINT)
RETURNS TABLE (section_id BIGINT, code VARCHAR) AS $$
    SELECT DISTINCT s.id, s.code
    FROM enrollment e
    JOIN section s     ON s.id = e.section_id
    JOIN meeting mine  ON mine.section_id = e.section_id
    JOIN meeting other ON other.section_id = p_section
    JOIN section ns    ON ns.id = p_section
    WHERE e.student_id = p_student
      AND e.status = 'ENROLLED'
      AND e.section_id <> p_section
      AND s.term_id = ns.term_id
      AND mine.weekday = other.weekday
      AND mine.start_time < other.end_time
      AND other.start_time < mine.end_time
      AND (mine.week_parity = 'ALL' OR other.week_parity = 'ALL'
           OR mine.week_parity = other.week_parity);
$$ LANGUAGE sql STABLE;

-- Przykład: zapis do grupy (fragment EnrollmentService).
--
--   BEGIN;
--   SELECT 1 FROM student WHERE user_id = :student FOR UPDATE;   -- serializuje zapisy studenta
--   SELECT ... FROM section WHERE id = :section FOR UPDATE;      -- serializuje zapisy do grupy
--   -- sprawdzenie: wymagania wstępne, schedule_conflicts(:student, :section),
--   -- brak innej grupy tego samego kursu i typu (kind), a przy braku miejsc:
--   -- liczba WAITING < section.waitlist_limit
--   UPDATE section SET enrolled_count = enrolled_count + 1, version = version + 1
--    WHERE id = :section AND enrolled_count < capacity;           -- 0 wierszy => lista oczekujących
--   INSERT INTO enrollment (...) VALUES (...);                    -- albo INSERT INTO waitlist_entry
--   COMMIT;
--
-- Wypis: w tej samej transakcji UPDATE enrollment SET status = 'DROPPED',
-- enrolled_count - 1, a potem awans pierwszego oczekującego, który spełnia
-- wymagania i nie ma kolizji (pozostałych oznaczamy SKIPPED z powodem).
