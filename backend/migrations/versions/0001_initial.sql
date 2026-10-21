-- System zapisów na zajęcia: schemat bazy danych (PostgreSQL 16), migracja 0001.
--
-- W bazie są tylko struktury i ograniczenia spójności (klucze, UNIQUE, CHECK).
-- Reguły biznesowe (kolizje, wymagania wstępne, "jedna grupa danego typu",
-- uprawnienia tur, cykle wymagań) są w kodzie aplikacji: app/domain.
-- Ograniczenia w bazie to siatka bezpieczeństwa na wypadek błędu w kodzie.

-- Użytkownicy -----------------------------------------------------------------

-- Kierunek studiów. Tury zapisów są otwierane osobno dla kierunków.
CREATE TABLE program (
    id   BIGSERIAL    PRIMARY KEY,
    code VARCHAR(20)  NOT NULL UNIQUE,                     -- np. INF, MAT
    name VARCHAR(200) NOT NULL
);

-- Jedna tabela użytkowników. Dane studenta i prowadzącego to kolumny
-- wypełniane tylko dla danej roli (pilnują tego CHECK-i poniżej).
CREATE TABLE app_user (
    id            BIGSERIAL    PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name     VARCHAR(200) NOT NULL,
    role          VARCHAR(16)  NOT NULL CHECK (role IN ('STUDENT', 'LECTURER', 'ADMIN')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- STUDENT
    index_no      VARCHAR(10)  UNIQUE,
    program_id    BIGINT       REFERENCES program(id),
    semester      SMALLINT     CHECK (semester BETWEEN 1 AND 12),
    -- LECTURER
    title         VARCHAR(50),
    department    VARCHAR(100),
    CHECK (num_nonnulls(index_no, program_id, semester) = CASE WHEN role = 'STUDENT' THEN 3 ELSE 0 END),
    CHECK ((role = 'LECTURER') = (department IS NOT NULL)),
    CHECK (title IS NULL OR role = 'LECTURER')
);
CREATE INDEX app_user_program ON app_user (program_id) WHERE role = 'STUDENT';

-- Katalog --------------------------------------------------------------------

CREATE TABLE course (
    id          BIGSERIAL    PRIMARY KEY,
    code        VARCHAR(20)  NOT NULL UNIQUE,
    name        VARCHAR(200) NOT NULL,
    ects        SMALLINT     NOT NULL CHECK (ects > 0),
    description TEXT
);

-- Brak cykli (A wymaga B, B wymaga A) sprawdza CatalogService pod blokadą,
-- CHECK łapie tylko pętlę A -> A.
CREATE TABLE course_prerequisite (
    course_id          BIGINT NOT NULL REFERENCES course(id) ON DELETE CASCADE,
    required_course_id BIGINT NOT NULL REFERENCES course(id),
    PRIMARY KEY (course_id, required_course_id),
    CHECK (course_id <> required_course_id)
);

-- Semestr. Tygodnie liczymy od starts_on: tydzień 1 (nieparzysty) zaczyna się
-- w poniedziałek tygodnia, w którym wypada starts_on.
CREATE TABLE term (
    id        BIGSERIAL   PRIMARY KEY,
    code      VARCHAR(10) NOT NULL UNIQUE,                  -- np. 2026Z
    starts_on DATE        NOT NULL,
    ends_on   DATE        NOT NULL,
    CHECK (starts_on < ends_on)
);

-- Tury zapisów w semestrze. Tura obejmuje wybrane kierunki (round_program),
-- tura bez kierunków jest dla wszystkich. Tury różnych kierunków mogą się
-- nakładać, a dziekanat rozkłada szczyt obciążenia, przesuwając godziny.
-- opens_at / closes_at to harmonogram dla workera. O tym, czy można się
-- zapisywać, decyduje status: worker zmienia go o zadanej godzinie (UC17),
-- a dziekanat może to zrobić ręcznie (UC16), np. przedłużyć turę po awarii.
CREATE TABLE enrollment_round (
    id        BIGSERIAL   PRIMARY KEY,
    term_id   BIGINT      NOT NULL REFERENCES term(id),
    name      VARCHAR(50) NOT NULL,
    opens_at  TIMESTAMPTZ NOT NULL,
    closes_at TIMESTAMPTZ NOT NULL,
    status    VARCHAR(16) NOT NULL DEFAULT 'PLANNED'
              CHECK (status IN ('PLANNED', 'OPEN', 'CLOSED')),
    UNIQUE (term_id, name),
    CHECK (opens_at < closes_at)
);
CREATE INDEX enrollment_round_term ON enrollment_round (term_id) WHERE status = 'OPEN';

CREATE TABLE round_program (
    round_id   BIGINT NOT NULL REFERENCES enrollment_round(id) ON DELETE CASCADE,
    program_id BIGINT NOT NULL REFERENCES program(id),
    PRIMARY KEY (round_id, program_id)
);

CREATE TABLE room (
    id       BIGSERIAL   PRIMARY KEY,
    building VARCHAR(20) NOT NULL,
    number   VARCHAR(20) NOT NULL,
    seats    SMALLINT    NOT NULL CHECK (seats > 0),
    UNIQUE (building, number)
);

-- Grupa zajęciowa (sekcja). Różne rozmiary grup: limit ustalany per grupa.
-- Limit nie może przekraczać liczby miejsc w sali (sprawdza CatalogService,
-- bo sala jest przypisana do terminu, nie do grupy).
CREATE TABLE section (
    id             BIGSERIAL   PRIMARY KEY,
    course_id      BIGINT      NOT NULL REFERENCES course(id),
    term_id        BIGINT      NOT NULL REFERENCES term(id),
    code           VARCHAR(10) NOT NULL,                   -- np. W01, C03, L12
    kind           VARCHAR(16) NOT NULL CHECK (kind IN ('LECTURE', 'EXERCISE', 'LAB', 'SEMINAR')),
    capacity       SMALLINT    NOT NULL CHECK (capacity > 0),
    enrolled_count SMALLINT    NOT NULL DEFAULT 0 CHECK (enrolled_count >= 0),
    waitlist_limit SMALLINT    NOT NULL DEFAULT 50 CHECK (waitlist_limit >= 0),
    UNIQUE (course_id, term_id, code),
    -- Chroni licznik (np. przed zmniejszeniem limitu poniżej liczby zapisanych).
    -- Nie chroni przed błędem, który zapisze studenta bez zwiększenia licznika -
    -- to wykrywa audyt niezmienników (app/services/audit.py).
    CHECK (enrolled_count <= capacity)
);
CREATE INDEX section_term ON section (term_id, course_id);

-- Klucz obcy nie sprawdza roli: że lecturer_id to prowadzący, pilnuje CatalogService.
CREATE TABLE section_lecturer (
    section_id  BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    lecturer_id BIGINT NOT NULL REFERENCES app_user(id),
    PRIMARY KEY (section_id, lecturer_id)
);
CREATE INDEX section_lecturer_lecturer ON section_lecturer (lecturer_id);

-- Harmonogram: cotygodniowe terminy grupy (grupa może mieć kilka terminów).
-- week_parity: ODD / EVEN = nieparzyste / parzyste tygodnie semestru (patrz term).
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

-- passed wyliczane z oceny, więc nie da się zapisać "2.0 i zaliczone".
CREATE TABLE completed_course (
    student_id BIGINT       NOT NULL REFERENCES app_user(id),
    course_id  BIGINT       NOT NULL REFERENCES course(id),
    term_id    BIGINT       NOT NULL REFERENCES term(id),
    grade      NUMERIC(2,1) NOT NULL CHECK (grade IN (2.0, 3.0, 3.5, 4.0, 4.5, 5.0)),
    passed     BOOLEAN      GENERATED ALWAYS AS (grade >= 3.0) STORED,
    PRIMARY KEY (student_id, course_id, term_id)
);

-- Zapisy ---------------------------------------------------------------------

-- student_id (tu i w completed_course) wskazuje na app_user, więc klucz obcy
-- nie sprawdza roli. Przy zapisie robi to blokada studenta na początku
-- transakcji (WHERE role = 'STUDENT'): brak wiersza = odmowa.
-- created_by / dropped_by: kto wykonał operację (sam student albo pracownik
-- dziekanatu); NULL, gdy zrobił to system (awans z listy).
CREATE TABLE enrollment (
    id          BIGSERIAL   PRIMARY KEY,
    student_id  BIGINT      NOT NULL REFERENCES app_user(id),
    section_id  BIGINT      NOT NULL REFERENCES section(id),
    status      VARCHAR(16) NOT NULL CHECK (status IN ('ENROLLED', 'DROPPED')),
    source      VARCHAR(16) NOT NULL CHECK (source IN ('DIRECT', 'WAITLIST', 'ADMIN')),
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dropped_at  TIMESTAMPTZ,
    created_by  BIGINT      REFERENCES app_user(id),
    dropped_by  BIGINT      REFERENCES app_user(id),
    CHECK ((status = 'DROPPED') = (dropped_at IS NOT NULL))
);
-- Historia wypisów zostaje, ale aktywny zapis do grupy może być tylko jeden.
-- ENROLLED zostaje też po końcu semestru, dlatego reguły zapisu zawsze
-- zawężają się do semestru grupy (section.term_id).
CREATE UNIQUE INDEX enrollment_one_active
    ON enrollment (student_id, section_id) WHERE status = 'ENROLLED';
CREATE INDEX enrollment_section ON enrollment (section_id) WHERE status = 'ENROLLED';

-- Kolejność na liście = id (nadawane z sekwencji przy INSERT, czyli pod blokadą
-- grupy, więc zgodne z kolejnością zapisów). created_at służy tylko do wyświetlania.
CREATE TABLE waitlist_entry (
    id            BIGSERIAL    PRIMARY KEY,
    student_id    BIGINT       NOT NULL REFERENCES app_user(id),
    section_id    BIGINT       NOT NULL REFERENCES section(id),
    status        VARCHAR(16)  NOT NULL DEFAULT 'WAITING'
                  CHECK (status IN ('WAITING', 'PROMOTED', 'SKIPPED', 'CANCELLED', 'EXPIRED')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    resolved_at   TIMESTAMPTZ,
    skip_reason   VARCHAR(255),
    enrollment_id BIGINT       UNIQUE REFERENCES enrollment(id),
    CHECK ((status = 'WAITING') = (resolved_at IS NULL)),
    CHECK ((status = 'PROMOTED') = (enrollment_id IS NOT NULL)),
    CHECK ((status = 'SKIPPED') = (skip_reason IS NOT NULL))
);
CREATE UNIQUE INDEX waitlist_one_waiting
    ON waitlist_entry (student_id, section_id) WHERE status = 'WAITING';
CREATE INDEX waitlist_queue
    ON waitlist_entry (section_id, id) WHERE status = 'WAITING';
CREATE INDEX waitlist_student
    ON waitlist_entry (student_id) WHERE status = 'WAITING';

-- Outbox powiadomień: zapis w tej samej transakcji co zmiana, wysyłka przez worker.
-- attempts: nieudane próby wysyłki (worker ponawia, po kilku odpuszcza).
CREATE TABLE notification (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES app_user(id),
    type       VARCHAR(32) NOT NULL,  -- PROMOTED | SKIPPED | CANCELLED | EXPIRED | ...
    payload    JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at    TIMESTAMPTZ,
    read_at    TIMESTAMPTZ,
    attempts   SMALLINT    NOT NULL DEFAULT 0
);
CREATE INDEX notification_unsent ON notification (id) WHERE sent_at IS NULL AND attempts < 5;
CREATE INDEX notification_user   ON notification (user_id, id);
