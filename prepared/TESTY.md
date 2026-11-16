# Etap 5 – scenariusze testowe

Zgodnie z wymaganiem każdy test ma trzy części: **1) przygotowanie** – ustawienie systemu w stanie
wyjściowym, **2) test** – wołanie konkretnych metod serwisów z konkretnymi parametrami,
**3) weryfikacja** – sprawdzenie zwróconych wyników i stanu systemu.

- **K1–K14** – brak kolizji w planie studenta (zapis, lista oczekujących, **awans z kolejki**,
  **zmiana harmonogramu w trakcie zapisów**, współbieżność) – algorytmy na metodach serwisów projektu.
- **P1–P12** – zapisy według preferencji – algorytmy na metodach serwisów projektu.
- **A1–A8** – algorytm przydziału – **zaimplementowane** w `prototyp/test_preference_allocator.py`
  (`python -m pytest test_preference_allocator.py` – 8 testów, wszystkie przechodzą).

Wywoływane metody pochodzą z projektu (README §6): `EnrollmentService.enroll / drop_section /
get_student_schedule`, `WaitingListService.join_waitlist / on_seat_freed / promote_next`,
`CatalogService.create_or_update_section / update_section_capacity / configure_enrollment_window /
get_available_seats`, `PreferenceService.save_preferences / get_preferences`,
`AllocationService.run_allocation / get_student_allocation`.

## Wspólne przygotowanie i narzędzia

```text
ŚWIAT (tworzony od nowa przed każdym testem, w pustej bazie):
  T   = Term(id=1, name="2026Z", is_active=True, enrollment_mode=FCFS,
             enrollment_start=teraz-1h, enrollment_end=teraz+1h)
  kursy: IO(id=10), BD(id=11), TS(id=12), AM1(id=13), ZIO(id=14, prerequisite_ids=[13])
  studenci (rola Student): U1..U6 = users.id 101..106
  ADMIN = users.id 1 (rola Admin)
  sekcja(id, kurs, capacity, terminy) = CatalogService.create_or_update_section(
        SectionDTO(id, term_id=1, course_id=kurs, lecturer_id=1, capacity, room="C2-"+id,
                   schedules=[ScheduleSlot(dzień, od, do), ...]), admin_id=1, ip="10.0.0.1")

Skróty terminów: PON10 = (MON, 10:00, 11:30), PON11 = (MON, 11:00, 12:30), WT10 = (TUE, 10:00, 11:30)

plan(u)      = { s.section_id for s in EnrollmentService.get_student_schedule(u, term_id=1) }
wolne(s)     = CatalogService.get_available_seats(s)
kolejka(s)   = [student_id z waiting_lists WHERE section_id = s ORDER BY created_at]
równolegle(f, g) = uruchom f i g w dwóch wątkach (osobne połączenia z bazą) jednocześnie
                   (bariera startowa); zwróć oba wyniki. Testy z „równolegle” powtarzamy 20 razy
                   na świeżych danych – różne przeplecenia transakcji.

kolizje_w_planach(term_id) – WYROCZNIA, zapytanie niezależne od EnrollmentRuleEngine:
  SELECT e1.student_id, e1.section_id, e2.section_id
  FROM enrollments e1
  JOIN enrollments e2 ON e2.student_id = e1.student_id AND e2.section_id > e1.section_id
  JOIN sections s1 ON s1.id = e1.section_id AND s1.term_id = :term_id
  JOIN sections s2 ON s2.id = e2.section_id AND s2.term_id = :term_id
  JOIN schedules h1 ON h1.section_id = s1.id
  JOIN schedules h2 ON h2.section_id = s2.id
  WHERE e1.status = 'ENROLLED' AND e2.status = 'ENROLLED'
    AND h1.day_of_week = h2.day_of_week
    AND h1.start_time < h2.end_time AND h2.start_time < h1.end_time
  -- pusty wynik = żaden student nie ma kolizji
```

Na końcu **każdego** testu K i P sprawdzamy dodatkowo: `kolizje_w_planach(1) == []`.

---

## K – brak kolizji w planie studenta

### K1. Zapis bezpośredni na sekcję kolidującą z planem
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); sekcja(202, BD, 15, [PON11])
                  EnrollmentService.enroll(101, 201, "10.0.0.7")        -> ResultDTO(ENROLLED)
2. TEST           r = EnrollmentService.enroll(101, 202, "10.0.0.7")
3. WERYFIKACJA    r.status == RULE_VIOLATION
                  r.details.code == "SCHEDULE_CONFLICT" and r.details.sections == [201]
                  plan(101) == {201};  wolne(202) == 15
                  brak wpisu audit_logs(action="ENROLL", section 202)
```

### K2. Granice przedziałów czasu (`ScheduleSlot.overlaps_with`, doprecyzowanie Z5)
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); enroll(101, 201, ip)
                  sekcja(202, BD, 15, [<termin z tabeli>])
2. TEST           r = EnrollmentService.enroll(101, 202, ip)
3. WERYFIKACJA    | termin sekcji 202          | oczekiwany r.status |
                  | (MON, 11:30, 13:00) – styk | ENROLLED            |
                  | (TUE, 10:00, 11:30)        | ENROLLED            |
                  | (MON, 09:00, 10:01)        | RULE_VIOLATION      |
                  | (MON, 10:30, 11:00)        | RULE_VIOLATION      |
```

### K3. Kolizja drugiego terminu sekcji
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [(THU, 08:00, 09:30)]); enroll(101, 201, ip)
                  sekcja(202, BD, 15, [PON10, (THU, 09:00, 10:30)])
2. TEST           r = EnrollmentService.enroll(101, 202, ip)
3. WERYFIKACJA    r.status == RULE_VIOLATION and r.details.sections == [201]; plan(101) == {201}
```

### K4. Nie można stanąć w kolejce do sekcji kolidującej z planem
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); enroll(101, 201, ip)
                  sekcja(202, BD, 1, [PON11]); enroll(102, 202, ip)          (202 pełna)
2. TEST           r = WaitingListService.join_waitlist(101, 202, ip)
3. WERYFIKACJA    r -> RULE_VIOLATION (kolizja z 201), 400; kolejka(202) == []
```

### K5. Awans z kolejki pomija osobę, która w międzyczasie zapisała się na kolidujące zajęcia
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 1, [PON10]); sekcja(202, BD, 15, [PON11])
                  enroll(101, 201) -> ENROLLED
                  join_waitlist(102, 201) -> 1;  join_waitlist(103, 201) -> 2
                  enroll(102, 202) -> ENROLLED        (102 tylko czeka na 201 – zapis na 202 legalny)
2. TEST           EnrollmentService.drop_section(101, 201, ip)            -> True
                  n = WaitingListService.on_seat_freed(201)            (zadanie Celery po SEAT_FREED)
3. WERYFIKACJA    n == 1
                  kolejne promote_next zwróciły: SKIPPED_CONFLICT (102), PROMOTED (103)
                  plan(102) == {202};  plan(103) == {201}
                  kolejka(201) == [102]               (pominięty zostaje w kolejce – jak w projekcie)
                  audit_logs: WAITLIST_PROMOTE dla 103, ip="SYSTEM"
```

### K6. Student czeka na dwie kolidujące ze sobą sekcje, obie zwalniają się jednocześnie
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 1, [PON10]); sekcja(202, BD, 1, [PON11])
                  enroll(101, 201); enroll(102, 202)
                  join_waitlist(103, 201) -> 1;  join_waitlist(103, 202) -> 1
                  drop_section(101, 201); drop_section(102, 202)  (zdarzenia SEAT_FREED w kolejce)
2. TEST           równolegle( on_seat_freed(201), on_seat_freed(202) )      × 20 powtórzeń
3. WERYFIKACJA    |plan(103) ∩ {201, 202}| == 1                (dokładnie jedna sekcja)
                  druga sekcja: promote_next zwróciło SKIPPED_CONFLICT dla 103, wolne == 1
                  jeżeli któreś zadanie dostało 55P03 (zablokowany kandydat) – zostało ponowione
                  (Celery retry) i dało ten sam końcowy wynik
```

### K7. Zwiększenie limitu awansuje tylko osoby bez kolizji
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 1, [PON10]); sekcja(202, BD, 15, [(MON, 09:00, 10:30)])
                  enroll(101, 201); join_waitlist(102..105, 201) -> pozycje 1..4
                  enroll(102, 202); enroll(104, 202)              (102 i 104 mają kolizję z 201)
2. TEST           CatalogService.update_section_capacity(201, new_cap=3, admin_id=1, ip)
                  n = WaitingListService.on_seat_freed(201)
3. WERYFIKACJA    n == 2;  zapisani na 201 == {101, 103, 105};  wolne(201) == 0
                  kolejka(201) == [102, 104]
```

### K8. Równoległe zapisy tego samego studenta na dwie kolidujące sekcje (luka Z1)
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); sekcja(202, BD, 15, [PON10])
2. TEST           (r1, r2) = równolegle( enroll(101, 201, ip), enroll(101, 202, ip) )   × 20
3. WERYFIKACJA    {r1.status, r2.status} == {ENROLLED, RULE_VIOLATION}
                  |plan(101)| == 1
UWAGA             W otrzymanym projekcie (check_rules przed BEGIN, blokada tylko sekcji) ten test
                  NIE przechodzi: oba wątki widzą pusty plan i oba zwracają ENROLLED.
                  Po zmianie (blokada studenta na początku transakcji) drugi wątek czeka
                  i widzi zapis pierwszego.
```

### K9. Wyścig: awans z kolejki kontra zapis kandydata na kolidującą sekcję (luka Z2)
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 1, [PON10]); sekcja(202, BD, 15, [PON11])
                  enroll(101, 201); join_waitlist(102, 201) -> 1; drop_section(101, 201)
2. TEST           (n, r) = równolegle( on_seat_freed(201), enroll(102, 202, ip) )    × 20
3. WERYFIKACJA    102 ma dokładnie jedną z {201, 202} (nigdy obie)
                  jeżeli 102 ∈ zapisani(201): r.status == RULE_VIOLATION
                  jeżeli 102 ∈ zapisani(202): promote_next zwróciło SKIPPED_CONFLICT
                                              (bezpośrednio albo po ponowieniu po 55P03)
```

### K10. Zmiana terminu kolidująca z planem zapisanego studenta jest odrzucana (UC11)
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); sekcja(202, BD, 15, [WT10])
                  enroll(101, 201); enroll(101, 202)
2. TEST           r = CatalogService.create_or_update_section(
                        SectionDTO(id=202, ..., schedules=[(MON, 10:30, 12:00)]), admin_id=1, ip)
3. WERYFIKACJA    wyjątek / 409 STUDENT_CONFLICT, details == [{student_id: 101, sections: [201]}]
                  terminy sekcji 202 nadal [WT10];  plan(101) == {201, 202}
                  brak wpisu audit_logs(action="SECTION_SCHEDULE_CHANGE")
```

### K11. Zmiana terminu bez kolizji przechodzi
```text
1. PRZYGOTOWANIE  jak K10
2. TEST           create_or_update_section(SectionDTO(id=202, ..., schedules=[(WED, 12:00, 13:30)]), 1, ip)
3. WERYFIKACJA    zwraca Section z terminem (WED, 12:00, 13:30)
                  get_student_schedule(101, 1) pokazuje 202 w środę 12:00
                  audit_logs: SECTION_SCHEDULE_CHANGE (user_id=1); cache available_seats:202 usunięty
```

### K12. Zmiana terminu tworzy kolizję u oczekującego – przy awansie jest pomijany
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); sekcja(202, BD, 1, [WT10])
                  enroll(102, 201)                       (102 ma poniedziałek 10:00)
                  enroll(101, 202); join_waitlist(102, 202) -> 1; join_waitlist(103, 202) -> 2
2. TEST           create_or_update_section(SectionDTO(id=202, schedules=[(MON, 10:30, 12:00)]), 1, ip)
                  drop_section(101, 202); n = on_seat_freed(202)
3. WERYFIKACJA    zmiana terminu przyjęta (102 tylko czeka – nie ma jeszcze miejsca)
                  n == 1; promote_next: SKIPPED_CONFLICT (102), PROMOTED (103)
                  plan(102) == {201};  plan(103) == {202}
```

### K13. Wyścig: zmiana terminu przez administratora kontra zapis studenta (luki Z3, Z4)
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); sekcja(202, BD, 15, [WT10])
                  wariant A: enroll(101, 201); cel = 202
                  wariant B: enroll(101, 202); cel = 201
2. TEST           (a, r) = równolegle(
                      create_or_update_section(SectionDTO(id=202, schedules=[(MON, 10:30, 12:00)]), 1, ip),
                      enroll(101, cel, ip) )                         × 20 dla każdego wariantu
3. WERYFIKACJA    dokładnie jedna operacja się udała:
                    (a = OK  i r.status == RULE_VIOLATION)   – zapis sprawdził już nowy termin
                  albo (a = STUDENT_CONFLICT / BUSY i r.status == ENROLLED)
                  nigdy obie naraz; kolizje_w_planach(1) == []
```

### K14. Kontrola wyroczni
```text
1. PRZYGOTOWANIE  sekcja(201, IO, 15, [PON10]); sekcja(202, BD, 15, [PON11]); enroll(101, 201)
2. TEST           INSERT INTO enrollments (student_id, section_id, status, source)
                  VALUES (101, 202, 'ENROLLED', 'DIRECT')     -- z pominięciem serwisów (symulacja błędu)
3. WERYFIKACJA    kolizje_w_planach(1) == [(101, 201, 202)]   – wyrocznia wykrywa kolizję,
                  więc pusty wynik w pozostałych testach coś znaczy
```

---

## P – zapisy według preferencji

Przygotowanie P (oprócz ŚWIATA): `CatalogService.configure_enrollment_window(1, teraz-1h, teraz+1h,
mode=PREFERENCES, points_budget=100, admin_id=1, ip)`; sekcje: IO-W `sekcja(301, IO, 100, [(WED, 08:00, 09:30)])`
– tylko jedna sekcja IO w wariancie „wykład”; IO-A `sekcja(302, IO, 1, [PON10])`, IO-B `sekcja(303, IO, 1, [WT10])`,
BD-A `sekcja(311, BD, 2, [PON10])`, TS-A `sekcja(321, TS, 4, [(WED, 12:00, 13:30)])`.
Zgłoszenie zapisujemy skrótem `P(kurs, waga, [sekcje w kolejności])`.

### P1. W trybie preferencji nie ma zapisu „kto pierwszy”
```text
1. PRZYGOTOWANIE  semestr w trybie PREFERENCES
2. TEST           r1 = EnrollmentService.enroll(101, 302, ip)
                  r2 = WaitingListService.join_waitlist(101, 302, ip)
3. WERYFIKACJA    r1.status == CLOSED (403); r2 -> CLOSED (403); plan(101) == {}
```

### P2. Zgłoszenie i jego zmiana w trakcie okna
```text
1. PRZYGOTOWANIE  –
2. TEST           a = PreferenceService.save_preferences(101, 1, [P(IO, 60, [303, 302]), P(BD, 40, [311])], ip)
                  b = PreferenceService.save_preferences(101, 1, [P(BD, 100, [311])], ip)
3. WERYFIKACJA    a.status == SAVED, a.used_points == 100, a.budget == 100
                  po b: get_preferences(101, 1) == [P(BD, 100, [311])]   (IO usunięte w całości)
                  section_preferences dla IO usunięte kaskadowo
                  audit_logs: 2 × SAVE_PREFERENCES
```

### P3. Niepoprawne zgłoszenia są odrzucane, poprzednie zostaje
```text
1. PRZYGOTOWANIE  save_preferences(101, 1, [P(BD, 10, [311])], ip) -> SAVED
2. TEST / 3. WERYFIKACJA   (za każdym razem: get_preferences(101, 1) nadal == [P(BD, 10, [311])])
   | wywołanie                                                  | wynik                       |
   | save_preferences(101, 1, [P(IO, 60, [302]), P(BD, 41, [311])]) | RULE_VIOLATION BUDGET_EXCEEDED |
   | save_preferences(101, 1, [P(IO, 10, [311])])               | RULE_VIOLATION BAD_SECTION  |
   | save_preferences(101, 1, [P(IO, 10, [302, 302])])          | DUPLICATE_SECTION           |
   | save_preferences(101, 1, [P(IO, 10, [302]), P(IO, 5, [303])]) | DUPLICATE_COURSE        |
   | save_preferences(101, 1, [P(IO, 0, [302])])                | BAD_WEIGHT                  |
   | po configure_enrollment_window(..., mode=FCFS): save_preferences(...) | CLOSED (403)     |
```

### P4. Ostrzeżenia przy zapisie zgłoszenia
```text
1. PRZYGOTOWANIE  sekcja(331, ZIO, 15, [(THU, 08:00, 09:30)])   (ZIO wymaga AM1; 101 nie zaliczył AM1)
                  101 ma już zapis ENROLLED na sekcji o terminie PON10 (z poprzedniej fazy FCFS)
2. TEST           r = save_preferences(101, 1, [P(ZIO, 20, [331]), P(BD, 30, [311]), P(IO, 50, [303])], ip)
3. WERYFIKACJA    r.status == SAVED (ostrzeżenia nie blokują)
                  r.warnings == [{course: ZIO, code: PREREQUISITES}, {course: BD, code: SCHEDULE_CONFLICT}]
```

### P5. Okno zamyka się w trakcie zapisu zgłoszenia
```text
1. PRZYGOTOWANIE  enrollment_end = teraz (okno właśnie minęło dla przydziału)
2. TEST           (s, a) = równolegle( save_preferences(102, 1, [P(BD, 50, [311])], ip),
                                       AllocationService.run_allocation(1, FINAL) )        × 20
3. WERYFIKACJA    albo s.status == SAVED i a.requests obejmuje (102, BD)
                  albo s.status == CLOSED i get_preferences(102, 1) == []
                  (FOR SHARE w save_preferences vs FOR UPDATE w run_allocation – nigdy „zgubione”)
```

### P6. Symulacja nie tworzy zapisów i trzyma tylko najnowszy wynik
```text
1. PRZYGOTOWANIE  save_preferences(101, 1, [P(IO, 70, [302])]); save_preferences(102, 1, [P(IO, 30, [302])])
2. TEST           r1 = run_allocation(1, PREVIEW); r2 = run_allocation(1, PREVIEW)
3. WERYFIKACJA    allocation_runs dla term 1 == [r2] (kind PREVIEW); enrollments – brak wierszy
                  get_student_allocation(101, 1).results == [{IO, ASSIGNED, section 302}]
                  get_student_allocation(102, 1).results == [{IO, UNASSIGNED, reason "Brak miejsc…"}]
```

### P7. Student reaguje na symulację zmianą wag
```text
1. PRZYGOTOWANIE  101: [P(IO, 50, [302]), P(BD, 50, [311])];  102: [P(IO, 40, [302]), P(BD, 60, [311])]
                  run_allocation(1, PREVIEW) -> IO dla 102: UNASSIGNED
2. TEST           save_preferences(102, 1, [P(IO, 90, [302]), P(BD, 10, [311])]); run_allocation(1, PREVIEW)
3. WERYFIKACJA    get_student_allocation(102, 1): IO == ASSIGNED (302)
```

### P8. Przydział końcowy – wynik, brak kolizji, jednorazowość
```text
1. PRZYGOTOWANIE  101: [P(IO, 70, [302, 303]), P(BD, 30, [311])]
                  102: [P(IO, 60, [302]),      P(BD, 40, [311])]
                  103: [P(IO, 20, [303]),      P(BD, 80, [311])]
                  enrollment_end = teraz-1min
2. TEST           r = run_allocation(1, FINAL);  r2 = run_allocation(1, FINAL)
3. WERYFIKACJA    r.assigned == 4:  102 -> 302 (IO), 101 -> 303 (IO, ustępuje 102), 101 -> 311, 103 -> 311
                  102: BD UNASSIGNED, reason FULL (2 miejsca 311 mają 103 i 101; i tak kolidowałaby z IO 302)
                  103: IO UNASSIGNED, reason FULL (303 zajęte przez 101 z wyższą wagą)
                  r.total_utility == 233 (wynik sprawdzony na prototypie PreferenceAllocator)
                  enrollments: source == 'ALLOCATION' dla wszystkich; wolne(302) == wolne(303) == 0
                  r2.status == SKIPPED; dokładnie 1 wiersz allocation_runs z kind = FINAL
                  ręczne INSERT drugiego FINAL -> naruszenie UNIQUE allocation_one_final
                  audit_logs: ALLOCATED dla 101, 102, 103 (ip="SYSTEM")
```

### P9. Zmiana terminu po złożeniu zgłoszenia jest uwzględniona
```text
1. PRZYGOTOWANIE  101: [P(IO, 60, [302]), P(TS, 40, [321])]
                  create_or_update_section(SectionDTO(id=302, schedules=[(WED, 12:30, 14:00)]), 1, ip)
                  (302 koliduje teraz z TS 321)
                  enrollment_end = teraz-1min
2. TEST           r = run_allocation(1, FINAL)
3. WERYFIKACJA    101 dostaje dokładnie jeden z kursów IO / TS (wyższa waga: IO 302)
                  TS: UNASSIGNED, reason zawiera "OWN_CONFLICT" / „koliduje z kursem…”
```

### P10. Przydział końcowy tylko po zakończeniu okna i tylko w trybie preferencji
```text
1. PRZYGOTOWANIE  okno otwarte (enrollment_end = teraz+1h)
2. TEST           r1 = run_allocation(1, FINAL)
                  configure_enrollment_window(1, ..., mode=FCFS, points_budget=None, 1, ip); r2 = run_allocation(1, FINAL)
3. WERYFIKACJA    r1.status == SKIPPED (okno trwa); r2.status == SKIPPED (tryb FCFS); brak zapisów
```

### P11. Remisy rozstrzyga ziarno – wynik odtwarzalny
```text
1. PRZYGOTOWANIE  101..106: każdy [P(IO, 50, [302])]   (302 ma 1 miejsce)
2. TEST           3 × run_allocation(1, PREVIEW, seed=12345)
3. WERYFIKACJA    za każdym razem ten sam, jeden student ASSIGNED; seed zapisany w allocation_runs
```

### P12. Zapisy uzupełniające po przydziale
```text
1. PRZYGOTOWANIE  jak P8 po run_allocation(1, FINAL)
2. TEST           configure_enrollment_window(1, teraz, teraz+2h, mode=FCFS, None, 1, ip)
                  r1 = enroll(103, 311, ip)        (103 ma już BD z przydziału -> duplikat kursu)
                  r2 = join_waitlist(103, 302, ip) (302 pełna)
                  configure_enrollment_window(1, ..., mode=PREFERENCES, 100, 1, ip)
3. WERYFIKACJA    r1.status == RULE_VIOLATION (DUPLICATE_COURSE); r2 -> pozycja 1
                  ponowne włączenie trybu PREFERENCES po FINAL -> odmowa ALREADY_ALLOCATED
```

---

## A – algorytm przydziału (zaimplementowane, `prototyp/test_preference_allocator.py`)

| Test | Przygotowanie | Wywołanie | Weryfikacja |
|---|---|---|---|
| A1 `test_overlaps_with_boundaries` | terminy PON 8:00–9:30 i inne | `overlaps_with` | 9:00–10:00 koliduje, 9:30–11:00 (styk) nie, inny dzień nie; `rank_factor(1,2,6,9) == 1.0, 0.9, 0.5, 0.5` |
| A2 `test_higher_weight_wins` | sekcja z 1 miejscem; wagi 30 i 70 | `allocate(..., seed=1)` | przydzielony student z wagą 70, drugi `FULL` |
| A3 `test_tie_decided_by_seed_reproducibly` | 8 osób, ta sama waga, 1 miejsce | `allocate` z ziarnami 0..19 | różne ziarna → różni zwycięzcy; to samo ziarno → ten sam wynik |
| A4 `test_no_conflict_between_assigned_courses` | dwa kursy o tej samej porze, wagi 30/70 | `allocate` | przydzielony kurs z wagą 70, drugi `OWN_CONFLICT` |
| A5 `test_plan_prerequisites_and_already_enrolled` | plan PON 8:00 z kursu 300, brak AM1 | `allocate` | `CONFLICT`, `PREREQUISITES`, `ALREADY_ENROLLED` |
| A6 `test_improvement_moves_flexible_student` | B (60) akceptuje S10, S11; A (50) tylko S10; po 1 miejscu | `allocate(improve=False)` i `allocate()` | zachłannie Σ = 60; z poprawą Σ = 104 (B → S11, A → S10) |
| A7 `test_quality_against_exact_optimum` | 300 losowych instancji | `allocate` vs przegląd zupełny | `verify == []` zawsze; średnio ≥ 99% optimum; ≥ 90% instancji dokładnie optymalnych; lepiej niż sam zachłanny |
| A8 `test_scale_one_program` | 1000 studentów × 6 kursów, 150 sekcji po 30 miejsc | `allocate` | < 30 s (zmierzone ok. 3 s), `verify == []` |

Każdy wynik `allocate` w testach A jest też sprawdzany przez `verify` (limity, kolizje, wymagania,
jedna sekcja kursu, sekcje tylko ze zgłoszenia).
