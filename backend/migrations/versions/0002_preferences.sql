-- Etap 5: zapisy według preferencji (wagi przedmiotów) i bezpieczna zmiana harmonogramu w trakcie tury.
--
-- Jak w 0001: w bazie struktura i ograniczenia spójności, decyzje (walidacja preferencji,
-- optymalizacja przydziału, wykrywanie kolizji) są w app/domain.

-- Tryb tury -------------------------------------------------------------------
-- QUEUE       - dotychczasowe zapisy "kto pierwszy, ten lepszy" z listami oczekujących,
-- PREFERENCES - w trakcie tury student tylko zgłasza i zmienia preferencje; miejsca
--               przydziela optymalizator po zamknięciu tury (allocation_run FINAL).
-- points_budget: pula punktów, którą student rozdziela między przedmioty (tylko PREFERENCES).
ALTER TABLE enrollment_round
    ADD COLUMN mode          VARCHAR(16) NOT NULL DEFAULT 'QUEUE' CHECK (mode IN ('QUEUE', 'PREFERENCES')),
    ADD COLUMN points_budget SMALLINT    CHECK (points_budget BETWEEN 1 AND 1000),
    ADD CONSTRAINT enrollment_round_budget CHECK ((mode = 'PREFERENCES') = (points_budget IS NOT NULL));

-- Wersja harmonogramu grupy ------------------------------------------------------
-- Zwiększana przy każdej zmianie terminów grupy (pod blokadą grupy). Zapis porównuje
-- ją z wersją danych katalogowych, na których sprawdził kolizje (cache procesu do 10 s);
-- różnica = dane nieaktualne -> ponowne sprawdzenie na świeżych terminach.
ALTER TABLE section ADD COLUMN schedule_version INTEGER NOT NULL DEFAULT 0;

-- Nowe źródło zapisu: przydział z tury preferencyjnej.
ALTER TABLE enrollment DROP CONSTRAINT enrollment_source_check;
ALTER TABLE enrollment ADD CONSTRAINT enrollment_source_check
    CHECK (source IN ('DIRECT', 'WAITLIST', 'ADMIN', 'ALLOCATION'));

-- Preferencje studenta --------------------------------------------------------------
-- Waga przedmiotu = ile punktów z puli student przeznacza na ten przedmiot. Suma wag
-- <= points_budget (sprawdza PreferenceService pod blokadą studenta - suma po wielu
-- wierszach nie da się wyrazić CHECK-iem).
CREATE TABLE course_preference (
    round_id   BIGINT      NOT NULL REFERENCES enrollment_round(id) ON DELETE CASCADE,
    student_id BIGINT      NOT NULL REFERENCES app_user(id),
    course_id  BIGINT      NOT NULL REFERENCES course(id),
    weight     SMALLINT    NOT NULL CHECK (weight > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (round_id, student_id, course_id)
);
CREATE INDEX course_preference_student ON course_preference (student_id);

-- Akceptowane grupy przedmiotu w kolejności (rank 1 = najbardziej chciana) - osobno dla
-- każdego typu zajęć (wykład, laboratorium...). Klucz obcy do course_preference: grupa
-- może być wybrana tylko w ramach zgłoszonego przedmiotu; usunięcie przedmiotu usuwa grupy.
-- Zgodność section.course_id z course_id i unikalność rangi w typie sprawdza walidacja.
CREATE TABLE section_preference (
    round_id   BIGINT   NOT NULL,
    student_id BIGINT   NOT NULL,
    course_id  BIGINT   NOT NULL,
    section_id BIGINT   NOT NULL REFERENCES section(id),
    rank       SMALLINT NOT NULL CHECK (rank >= 1),
    PRIMARY KEY (round_id, student_id, section_id),
    FOREIGN KEY (round_id, student_id, course_id)
        REFERENCES course_preference (round_id, student_id, course_id) ON DELETE CASCADE
);

-- Przebiegi optymalizatora ----------------------------------------------------------
-- PREVIEW - symulacja w trakcie tury (worker co kilka minut): student widzi przewidywany
--           wynik i może zmienić wagi; nic nie zapisuje do enrollment,
-- FINAL   - przydział po zamknięciu tury; najwyżej jeden na turę (indeks poniżej), więc
--           ponowne uruchomienie przez worker po awarii nie zapisze nikogo dwa razy.
-- seed: ziarno losowania kolejności przy remisach - przebieg da się odtworzyć.
-- upper_bound: suma wag wszystkich wykonalnych zgłoszeń (górne ograniczenie wyniku).
CREATE TABLE allocation_run (
    id            BIGSERIAL     PRIMARY KEY,
    round_id      BIGINT        NOT NULL REFERENCES enrollment_round(id) ON DELETE CASCADE,
    kind          VARCHAR(8)    NOT NULL CHECK (kind IN ('PREVIEW', 'FINAL')),
    seed          BIGINT        NOT NULL,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    students      INTEGER       NOT NULL CHECK (students >= 0),
    requests      INTEGER       NOT NULL CHECK (requests >= 0),
    assigned      INTEGER       NOT NULL CHECK (assigned BETWEEN 0 AND requests),
    total_utility NUMERIC(12,2) NOT NULL CHECK (total_utility >= 0),
    upper_bound   NUMERIC(12,2) NOT NULL CHECK (upper_bound >= total_utility)
);
CREATE UNIQUE INDEX allocation_one_final ON allocation_run (round_id) WHERE kind = 'FINAL';
CREATE INDEX allocation_run_round ON allocation_run (round_id, id);

-- Wynik dla każdego zgłoszonego przedmiotu: przydzielony (z użytecznością) albo nie (z powodem).
CREATE TABLE allocation_result (
    run_id     BIGINT       NOT NULL REFERENCES allocation_run(id) ON DELETE CASCADE,
    student_id BIGINT       NOT NULL REFERENCES app_user(id),
    course_id  BIGINT       NOT NULL REFERENCES course(id),
    weight     SMALLINT     NOT NULL CHECK (weight > 0),
    status     VARCHAR(12)  NOT NULL CHECK (status IN ('ASSIGNED', 'UNASSIGNED')),
    utility    NUMERIC(8,2) NOT NULL DEFAULT 0 CHECK (utility >= 0),
    reason     VARCHAR(255),
    PRIMARY KEY (run_id, student_id, course_id),
    CHECK ((status = 'UNASSIGNED') = (reason IS NOT NULL))
);
CREATE INDEX allocation_result_student ON allocation_result (student_id, run_id);

-- Grupy przydzielone w ramach przedmiotu (po jednej na typ zajęć).
CREATE TABLE allocation_assignment (
    run_id     BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    course_id  BIGINT NOT NULL,
    section_id BIGINT NOT NULL REFERENCES section(id),
    PRIMARY KEY (run_id, student_id, section_id),
    FOREIGN KEY (run_id, student_id, course_id)
        REFERENCES allocation_result (run_id, student_id, course_id) ON DELETE CASCADE
);
