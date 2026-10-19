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

-- Wymagania nie mogą tworzyć cyklu (A wymaga B, B wymaga A) - nikt nie mógłby
-- zapisać się na żaden z tych kursów. CHECK łapie tylko pętlę A -> A.
CREATE FUNCTION prevent_prerequisite_cycle() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE required(id) AS (
            SELECT NEW.required_course_id
            UNION
            SELECT p.required_course_id
            FROM course_prerequisite p JOIN required r ON p.course_id = r.id
        )
        SELECT 1 FROM required WHERE id = NEW.course_id
    ) THEN
        RAISE EXCEPTION 'cykl wymagań wstępnych: kurs % pośrednio wymaga sam siebie', NEW.course_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER course_prerequisite_no_cycle
    BEFORE INSERT OR UPDATE ON course_prerequisite
    FOR EACH ROW EXECUTE FUNCTION prevent_prerequisite_cycle();

-- Semestr. Tygodnie liczymy od starts_on: tydzień 1 (nieparzysty) zaczyna się
-- w poniedziałek tygodnia, w którym wypada starts_on.
CREATE TABLE term (
    id        BIGSERIAL   PRIMARY KEY,
    code      VARCHAR(10) NOT NULL UNIQUE,                  -- np. 2026Z
    starts_on DATE        NOT NULL,
    ends_on   DATE        NOT NULL,
    CHECK (starts_on < ends_on)
);

-- Tury zapisów w semestrze (np. tura 1 - tylko swój kierunek, tura 2 - wszyscy).
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
-- W danym semestrze otwarta jest najwyżej jedna tura.
CREATE UNIQUE INDEX enrollment_round_one_open
    ON enrollment_round (term_id) WHERE status = 'OPEN';

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
    -- to wykrywa widok section_invariant_violations.
    CHECK (enrolled_count <= capacity)
);

CREATE TABLE section_lecturer (
    section_id  BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    lecturer_id BIGINT NOT NULL REFERENCES lecturer(user_id),
    PRIMARY KEY (section_id, lecturer_id)
);

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
    student_id BIGINT       NOT NULL REFERENCES student(user_id),
    course_id  BIGINT       NOT NULL REFERENCES course(id),
    term_id    BIGINT       NOT NULL REFERENCES term(id),
    grade      NUMERIC(2,1) NOT NULL CHECK (grade IN (2.0, 3.0, 3.5, 4.0, 4.5, 5.0)),
    passed     BOOLEAN      GENERATED ALWAYS AS (grade >= 3.0) STORED,
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
-- ENROLLED zostaje też po końcu semestru, dlatego reguły zapisu zawsze
-- zawężają się do semestru grupy (section.term_id).
CREATE UNIQUE INDEX enrollment_one_active
    ON enrollment (student_id, section_id) WHERE status = 'ENROLLED';
CREATE INDEX enrollment_student ON enrollment (student_id) WHERE status = 'ENROLLED';

-- Kolejność na liście = id (nadawane z sekwencji przy INSERT, czyli pod blokadą
-- grupy, więc zgodne z kolejnością zapisów). created_at służy tylko do wyświetlania.
CREATE TABLE waitlist_entry (
    id            BIGSERIAL    PRIMARY KEY,
    student_id    BIGINT       NOT NULL REFERENCES student(user_id),
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

-- Outbox powiadomień: zapis w tej samej transakcji co zmiana, wysyłka przez worker.
CREATE TABLE notification (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES app_user(id),
    type       VARCHAR(32) NOT NULL,  -- PROMOTED | SKIPPED | CANCELLED | EXPIRED | ...
    payload    JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at    TIMESTAMPTZ
);
CREATE INDEX notification_unsent ON notification (created_at) WHERE sent_at IS NULL;

-- Reguły zapisu --------------------------------------------------------------

-- Grupy z planu studenta, których terminy nachodzą na terminy grupy p_section.
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

-- Grupa tego samego kursu i typu w TYM SAMYM semestrze, do której student jest
-- już zapisany (wykład + laboratorium z IO - wolno, dwa laboratoria - nie).
-- Bez warunku na semestr zapis z poprzedniego roku blokowałby powtarzanie kursu.
CREATE FUNCTION same_course_kind_section(p_student BIGINT, p_section BIGINT)
RETURNS TABLE (section_id BIGINT, code VARCHAR) AS $$
    SELECT s.id, s.code
    FROM enrollment e
    JOIN section s  ON s.id = e.section_id
    JOIN section ns ON ns.id = p_section
    WHERE e.student_id = p_student
      AND e.status = 'ENROLLED'
      AND s.id <> ns.id
      AND s.term_id = ns.term_id
      AND s.course_id = ns.course_id
      AND s.kind = ns.kind;
$$ LANGUAGE sql STABLE;

-- Audyt niezmienników (test regresyjny, okresowe sprawdzenie przez worker).
-- Pusty wynik = wszystko w porządku.
CREATE VIEW section_invariant_violations AS
    SELECT s.id AS section_id, 'licznik <> liczba zapisanych' AS problem
    FROM section s
    LEFT JOIN enrollment e ON e.section_id = s.id AND e.status = 'ENROLLED'
    GROUP BY s.id
    HAVING s.enrolled_count <> COUNT(e.id)
  UNION ALL
    SELECT DISTINCT s.id, 'wolne miejsca, a ktoś czeka na liście'
    FROM section s JOIN waitlist_entry w ON w.section_id = s.id AND w.status = 'WAITING'
    WHERE s.enrolled_count < s.capacity
  UNION ALL
    SELECT w.section_id, 'student jednocześnie zapisany i oczekujący'
    FROM waitlist_entry w
    JOIN enrollment e ON e.student_id = w.student_id AND e.section_id = w.section_id
    WHERE w.status = 'WAITING' AND e.status = 'ENROLLED';

-- Przykład: zapis do grupy (fragment EnrollmentService).
--
--   BEGIN;
--   SELECT 1 FROM student WHERE user_id = :student FOR UPDATE;   -- 1. blokada studenta
--   SELECT ... FROM section WHERE id = :section FOR UPDATE;      -- 2. blokada grupy
--   -- sprawdzenia (każde z odmową z podaniem przyczyny):
--   --   tura semestru grupy ma status OPEN,
--   --   student nie jest już zapisany ani nie czeka na tę grupę,
--   --   same_course_kind_section(:student, :section) jest puste,
--   --   wymagania wstępne zaliczone (completed_course.passed),
--   --   schedule_conflicts(:student, :section) jest puste,
--   --   przy braku miejsc: liczba WAITING < section.waitlist_limit
--   UPDATE section SET enrolled_count = enrolled_count + 1
--    WHERE id = :section AND enrolled_count < capacity;           -- 0 wierszy => lista oczekujących
--   INSERT INTO enrollment (...) VALUES (...);                    -- albo INSERT INTO waitlist_entry
--   -- po zapisie: wpisy WAITING studenta w innych grupach tego kursu i typu
--   -- (w tym semestrze) dostają status CANCELLED + powiadomienie
--   COMMIT;
--
-- Wypis (UC6) / zmiana limitu (UC13): w tej samej transakcji zmiana licznika
-- lub limitu, a potem awans z listy (UC9): dopóki są wolne miejsca, bierzemy
-- pierwszego WAITING (ORDER BY id) i sprawdzamy jego reguły jak wyżej.
--
-- Blokady przy awansie. Transakcja trzyma już blokadę grupy, a potrzebuje
-- blokady awansowanego studenta B (jego plan musi być stały w czasie
-- sprawdzania). To odwrotna kolejność niż przy zapisie (student -> grupa),
-- więc czekanie groziłoby zakleszczeniem z zapisem B do tej samej grupy:
--
--   SELECT 1 FROM student WHERE user_id = :b FOR UPDATE NOWAIT;
--
-- Jeśli B jest w tej chwili zablokowany (SQLSTATE 55P03), cała transakcja jest
-- wycofywana i ponawiana po chwili - nie pomijamy B, bo straciłby kolejkę.
-- Tak samo (ROLLBACK + ponowienie, maks. kilka prób) EnrollmentService obsługuje
-- 40P01 (deadlock) i 40001 (serialization failure) jako zabezpieczenie.
--
-- Zamknięcie tury (UC16/UC17): status CLOSED, a wszystkie wpisy WAITING
-- w grupach tego semestru dostają EXPIRED + powiadomienie. Wypis przez
-- dziekanat po turze nie uruchamia więc nikomu zapisu.
--
-- Decyzja dziekanatu (UC14, source = 'ADMIN'): może pominąć wymagania wstępne
-- i działać poza turą. Kolizje i regułę "jedna grupa danego typu" sprawdzamy
-- zawsze. Zapis do pełnej grupy = capacity + 1 w tej samej transakcji (CHECK
-- nadal obowiązuje, kolejka nie traci miejsca), ale nie ponad liczbę miejsc w sali.
