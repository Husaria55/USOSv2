# Etap 5 – scenariusze testowe

Wymaganie: *„weryfikacja braku kolizji zajęć dla studenta w różnych scenariuszach zapisu do grup
i zmiany harmonogramu w trakcie zapisów, szczególnie w kontekście przydzielania zajęć z kolejki”*.
Każdy scenariusz jest **zaimplementowany** jako test automatyczny (pytest, prawdziwy PostgreSQL 16)
i składa się z trzech części:

1. **Przygotowanie** – stan systemu tworzony fabrykami `tests/factories.py`
   (`f.section(course, term, code, capacity, meetings=[(dzień, od, do[, parzystość])])`, `f.student(program)` …),
2. **Test** – wywołania metod serwisów z konkretnymi parametrami
   (`EnrollmentService.enroll / drop / change_limits`, `CatalogService.update_meeting / add_meeting`,
   `PreferenceService.save_preferences`, `AllocationService.run_allocation`, `allocate()` …),
3. **Weryfikacja** – wynik metody (status, kod odmowy, zdarzenia awansu), stan bazy (plan, licznik,
   lista oczekujących, wersja harmonogramu, powiadomienia) oraz **audyt niezmienników**.

**Wyrocznia.** Po każdym scenariuszu wywoływane jest `audit.violations()` (`assert_no_violations`).
W etapie 5 audyt dostał dwa nowe niezmienniki: *„student ma kolizję z grupą X”* i *„student ma drugą
grupę tego samego typu”*. Kolizje liczy **w SQL, niezależnie od kodu domeny** (`app/domain/schedule.py`),
więc test nie sprawdza kodu tym samym kodem. Scenariusz K17 dowodzi, że wyrocznia wykrywa kolizję.

Uruchomienie: `docker compose up -d db && cd backend && uv run python -m pytest` → **96 testów**
(35 z etapu 3 + 61 nowych), ok. 45 s.

| Plik | Co | Testów |
|---|---|---|
| `tests/test_collisions.py` | K1–K17: kolizje przy zapisie, listach, awansie, zmianie harmonogramu, wyścigi | 23 |
| `tests/test_preferences.py` | P1–P13: tura preferencyjna na bazie i przez API | 17 |
| `tests/test_allocation_domain.py` | A1–A12: optymalizator bez bazy, jakość vs optimum, skala | 21 |
| pozostałe (etap 3) | domena, zapisy, wyścigi, API, worker | 35 |

Oznaczenia terminów: `PON 10` = poniedziałek 10:00–11:30 (`MON_10`), `WT 10` = wtorek 10:00–11:30.

---

## K – brak kolizji w planie studenta

### Zapis bezpośredni

**K1. Zapis do grupy nachodzącej na plan jest odrzucany** – `test_k1_direct_enrollment_with_conflict_is_refused`
```
PRZYGOTOWANIE  io_l1 = section(IO, "L01", PON 10);  bd_l1 = section(BD, "L01", pon 11:00–12:30)
               st = student(INF);  enroll(st, io_l1)                  -> ENROLLED
TEST           enroll(st, bd_l1, mode=DIRECT)
WERYFIKACJA    wyjątek Conflict, code == "CONFLICT", details == ["IO L01"]
               plan(st) == {IO L01};  bd_l1.enrolled_count == 0;  audyt pusty
```

**K2. Granice przedziałów** – `test_k2_time_boundaries` (4 przypadki, parametryzacja)
```
PRZYGOTOWANIE  a = section(PON 10); b = section(<termin>); enroll(st, a)
TEST           enroll(st, b)
WERYFIKACJA    pon 11:30–13:00 (styk końcem)    -> ENROLLED
               wt 10:00–11:30 (inny dzień)      -> ENROLLED
               pon 09:00–10:01 (minuta wspólna) -> CONFLICT
               pon 10:30–11:00 (zawiera się)    -> CONFLICT
```

**K3. Parzystość tygodni** – `test_k3_week_parity` (4 przypadki)
```
PRZYGOTOWANIE  a = section(śr 12:00–13:30, <p1>); b = section(śr 12:00–13:30, <p2>); enroll(st, a)
TEST           enroll(st, b)
WERYFIKACJA    ODD/EVEN -> ENROLLED;  ODD/ODD, ODD/ALL, EVEN/ALL -> CONFLICT
```

**K4. Kolizja drugiego terminu grupy (także dla dziekanatu)** – `test_k4_second_meeting_of_section_collides`
```
PRZYGOTOWANIE  a = section(czw 8:00–9:30); b = section([PON 10, czw 9:00–10:30]); enroll(st, a)
TEST           enroll(st, b, DIRECT);  enroll(st, b, ADMIN, actor=dziekanat)
WERYFIKACJA    oba: CONFLICT (dziekanat może pominąć limit i wymagania, ale nie kolizję)
```

### Listy oczekujących i awans z kolejki

**K5. Nie można stanąć w kolejce do grupy kolidującej z planem** – `test_k5_cannot_join_waitlist_of_colliding_section`
```
PRZYGOTOWANIE  full = section(capacity=1, pon 11:00–12:00); enroll(other, full)
               a = section(PON 10); enroll(st, a)
TEST           enroll(st, full)
WERYFIKACJA    CONFLICT (a nie WAITLISTED);  lista oczekujących full == []
```

**K6. Oczekujący zapisał się w międzyczasie na kolidujące zajęcia – przy awansie jest pomijany** –
`test_k6_waiting_student_who_enrolled_elsewhere_is_skipped`
```
PRZYGOTOWANIE  a = section(AAA, capacity=1, PON 10);  b = section(BBB, pon 11:00–12:00)
               enroll(s0, a) -> ENROLLED;  enroll(s1, a) -> WAITLISTED poz. 1;  enroll(s2, a) -> poz. 2
               enroll(s1, b) -> ENROLLED            (s1 tylko czeka na A – zapis do B jest legalny)
TEST           events = drop(s0, a)                 (UC6 + awans UC9 w tej samej transakcji)
WERYFIKACJA    events == [(s1, SKIPPED, "Kolizja w planie z: BBB L01."), (s2, PROMOTED)]
               plan(s1) == {BBB L01};  plan(s2) == {AAA L01}
               powiadomienia == [(s1, SKIPPED), (s2, PROMOTED)];  audyt pusty
```

**K7. Czeka na dwie kolidujące grupy, obie zwalniają się jednocześnie** – `test_k7_waiting_on_two_colliding_sections_gets_at_most_one` (5 powtórzeń)
```
PRZYGOTOWANIE  a = section(capacity=1, PON 10); b = section(capacity=1, pon 11:00–12:00)
               enroll(ha, a); enroll(hb, b); enroll(st, a) -> WAITLISTED; enroll(st, b) -> WAITLISTED
TEST           równolegle: drop(ha, a) || drop(hb, b)    (dwa awanse tego samego studenta)
WERYFIKACJA    st jest dokładnie w jednej z grup;  statusy wpisów == {PROMOTED, SKIPPED};  audyt pusty
```
Dwa awanse blokują studenta `FOR UPDATE NOWAIT`; przegrany dostaje 55P03 i jest ponawiany, a wtedy
widzi już nowy plan.

**K8. Zwiększenie limitu awansuje tylko osoby bez kolizji** – `test_k8_capacity_increase_promotes_only_non_conflicting`
```
PRZYGOTOWANIE  a = section(capacity=1, PON 10); clash = section(pon 9:00–10:30)
               enroll(s0, a); w1..w4 czekają na a (w tej kolejności); enroll(w1, clash); enroll(w3, clash)
TEST           change_limits(a, capacity=3)          (UC13)
WERYFIKACJA    events == [(w1,SKIPPED),(w2,PROMOTED),(w3,SKIPPED),(w4,PROMOTED)]
               a: enrolled_count == capacity == 3, zapisani {s0, w2, w4}, lista pusta
```

**K9. Wyścig: awans z kolejki kontra zapis tego samego studenta do kolidującej grupy** –
`test_k9_promotion_races_with_direct_enrollment_of_same_student` (10 powtórzeń)
```
PRZYGOTOWANIE  a = section(capacity=1, PON 10); b = section(pon 11:00–12:00); enroll(h, a); enroll(st, a) -> czeka
TEST           równolegle: drop(h, a) || enroll(st, b)
WERYFIKACJA    st w dokładnie jednej z grup (nigdy w obu);  jeśli w A – enroll(st, b) dostał CONFLICT
```

### Zmiana harmonogramu w trakcie tury (UC32)

**K10. Przeniesienie terminu kolidujące z planem zapisanego studenta jest odrzucane** –
`test_k10_schedule_change_refused_when_enrolled_student_would_collide`
```
PRZYGOTOWANIE  a = section(AAA, PON 10); b = section(BBB, WT 10); enroll(st, a); enroll(st, b)
               m = meeting_of(b); v = b.schedule_version
TEST           update_meeting(m, weekday=1, start=10:30, end=12:00, parity=ALL, room=None)
WERYFIKACJA    Conflict STUDENT_CONFLICT, details == ["<nr indeksu>: AAA L01"]
               termin m nadal wt 10:00;  b.schedule_version == v;  audyt pusty
```

**K11. Zmiana bez kolizji: nowa wersja harmonogramu i powiadomienia** – `test_k11_schedule_change_allowed_bumps_version_and_notifies`
```
PRZYGOTOWANIE  a = section(PON 10); b = section(capacity=1, WT 10); st zapisany do a i b; waiting czeka na b
TEST           update_meeting(meeting_of(b), 3, 12:00, 13:30)
WERYFIKACJA    b.schedule_version == v + 1;  SCHEDULE_CHANGED dla {st, waiting}
               plan(st) pokazuje b w śr 12:00;  audyt pusty
```

**K12. Dodatkowy termin też jest sprawdzany względem zapisanych** – `test_k12_adding_meeting_checks_enrolled_students`
```
PRZYGOTOWANIE  st zapisany do a (PON 10) i b (WT 10)
TEST           add_meeting(b, 1, 11:00, 12:00, ALL, None)  ;  drop(st, a)  ;  add_meeting(...) ponownie
WERYFIKACJA    1. STUDENT_CONFLICT;  2. po wypisie z a – termin dodany (id > 0)
```

**K13. Zmiana terminu tworzy kolizję u OCZEKUJĄCEGO – przy awansie jest pomijany** –
`test_k13_schedule_change_for_waiting_student_leads_to_skip`
```
PRZYGOTOWANIE  a = section(PON 10); b = section(capacity=1, WT 10)
               enroll(w1, a); enroll(h, b); w1 i w2 czekają na b
TEST           update_meeting(meeting_of(b), 1, 10:30, 12:00)   -> dozwolone (w1 nie jest zapisany)
               events = drop(h, b)
WERYFIKACJA    events == [(w1, SKIPPED), (w2, PROMOTED)];  audyt pusty
```

**K14. Nieaktualny cache terminów (inny proces API) nie przepuszcza kolizji** –
`test_k14_stale_cached_schedule_does_not_let_conflict_through`
```
PRZYGOTOWANIE  a = section(AAA, PON 10); b = section(BBB, WT 10); enroll(st, a)
               load_target(b)                       -> cache procesu: b we wtorek, wersja v
               update_meeting(meeting_of(b), 1, 10:30, 12:00)   (bez forget_targets – jak inny proces)
               load_target(b) zwraca TEN SAM obiekt z wtorkiem   (dowód, że cache jest nieaktualny)
TEST           enroll(st, b)
WERYFIKACJA    CONFLICT (pod blokadą grupy wersja v+1 ≠ v -> świeże terminy -> ponowne check_student)
               plan(st) == {AAA L01}
```

**K15. Awans z kolejki używa aktualnego terminu, nie z cache** – `test_k15_promotion_uses_current_schedule_not_cache`
```
PRZYGOTOWANIE  enroll(w, a=PON 10); enroll(h, b=WT 10, capacity=1); enroll(w, b) -> czeka (cache: wtorek)
               update_meeting(meeting_of(b), 1, 11:00, 12:00)
TEST           events = drop(h, b)
WERYFIKACJA    events == [(w, SKIPPED)]
```

**K16. Wyścig: zmiana terminu przez dziekanat kontra zapis studenta** – `test_k16_schedule_change_races_with_enrollment` (2 warianty × 6 powtórzeń)
```
PRZYGOTOWANIE  a = section(PON 10); b = section(WT 10)
               wariant 1: enroll(st, a), cel = b;   wariant 2: enroll(st, b), cel = a
TEST           równolegle: update_meeting(meeting_of(b), 1, 10:30, 12:00) || enroll(st, cel)
WERYFIKACJA    kody wyników ∈ { [CONFLICT, OK], [OK, STUDENT_CONFLICT] }  – nigdy oba OK
               audyt pusty po każdym powtórzeniu
```
Wariant 2 sprawdza blokadę studentów `NOWAIT` w `update_meeting`. Po jej usunięciu test pada
(sprawdzone ręcznie mutacją kodu). Wariant 1 sprawdza `schedule_version`: po wyłączeniu porównania
wersji padają K13–K16.

**K17. Kontrola wyroczni** – `test_k17_audit_detects_conflict_written_around_the_rules`
```
PRZYGOTOWANIE  enroll(st, a=PON 10); b = section(pon 11:00–12:00)
TEST           INSERT INTO enrollment (st, b) z pominięciem serwisu (symulacja błędu w kodzie)
WERYFIKACJA    audit.violations() == ["student <st> ma kolizję z grupą <b>"]
```

---

## P – tura preferencyjna (baza danych + API)

Wspólne przygotowanie (`world`): kierunek INF, otwarta tura `PREFERENCES` z pulą 100 pkt; IO: wykład
W01 (śr 8:00, 100 miejsc), L01 (PON 10, 1 miejsce), L02 (WT 10, 1 miejsce); BD: L01 (PON 10, 2 miejsca).

| Test | Przygotowanie | Wywołanie | Oczekiwany wynik |
|---|---|---|---|
| **P1** `test_p1_preference_round_blocks_queue_operations` | student INF | `enroll(st, IO L01)`, `drop(st, IO L01)` | oba `ROUND_CLOSED` (w turze preferencyjnej nie ma kolejki) |
| **P2** `test_p2_save_and_modify_preferences` | – | `save_preferences(st, r, [IO 60: (L02, W01, L01)], [BD 40: (L01)])`, potem `save_preferences(st, r, [BD 100])` | `used_points == 100`; rangi per typ: L02=1, L01=2, W01=1; po zmianie zostaje tylko BD 100 |
| **P3** `test_p3_invalid_submissions_are_refused` (5 przypadków) | zapisane BD 10 | IO 60 + BD 41 / grupa BD dla IO / tura kolejkowa / student MAT / tura zamknięta | `BUDGET_EXCEEDED`, `BAD_SECTION`, `NOT_PREFERENCE_ROUND`, `ROUND_CLOSED`, `ROUND_CLOSED`; poprzednie zgłoszenie (BD 10) nietknięte |
| **P4** `test_p4_warnings_show_problems_early` | ZIO wymaga AM1 (brak); student ma zajęcia PON 10 | `save_preferences(ZIO 20, BD 30, IO 50)` | przyjęte; ostrzeżenia `{ZIO: PREREQUISITES, BD: CONFLICT}` |
| **P5** `test_p5_save_racing_with_round_close` (6×) | nowa tura | równolegle `save_preferences` ‖ `close_round` | albo `ROUND_CLOSED` i nic nie zapisano, albo zapisane **i** uwzględnione w przydziale (`requests == 1`) |
| **P6** `test_p6_preview_does_not_enroll_and_keeps_latest_only` | a: IO 70, b: IO 30 (L01 ma 1 miejsce) | 2× `run_allocation(r, PREVIEW)` | jeden przebieg PREVIEW (najnowszy), 0 zapisów; a: ASSIGNED [IO L01, IO W01]; b: UNASSIGNED „Brak miejsc…” |
| **P7** `test_p7_student_reacts_to_preview_by_changing_weights` | a: IO 50/BD 50, b: IO 40/BD 60 | PREVIEW → b podnosi IO do 90 → PREVIEW | IO u b: UNASSIGNED → ASSIGNED |
| **P8** `test_p8_final_allocation_end_to_end` | a: IO 70 (L01,L02) + BD 30; b: IO 60 (tylko L01) + BD 40; c: IO 20 (L02) + BD 80 | `close_round`, 2× `worker.allocate_closed_rounds()` | b dostaje IO L01 (a ustępuje do L02), c dostaje BD; nikt nie ma IO L01 i BD L01 (PON 10) naraz; źródło `ALLOCATION`; 1 przebieg FINAL; powiadomienia ALLOCATED/NOT_ALLOCATED; ponowny FINAL i ponowne otwarcie tury → `ALREADY_ALLOCATED`; audyt pusty |
| **P9** `test_p9_final_allocation_respects_existing_plans_and_seats_taken_meanwhile` | student zgłasza BD 50, IO 50; potem 2 studentów MAT zapełnia BD L01 (równoległa tura kolejkowa), dziekanat zapisuje go do IO L02 | `close_round`, `run_allocation(FINAL)` | przydzielony tylko brakujący wykład IO; plan {IO L02, IO W01}; BD: UNASSIGNED „Brak miejsc” |
| **P10** `test_p10_final_requires_closed_round` | – | FINAL w otwartej turze / w turze kolejkowej | `ROUND_NOT_CLOSED` / `NOT_PREFERENCE_ROUND` |
| **P11** `test_p11_allocation_is_reproducible_with_seed` | 6 osób, IO 50, L01 ma 1 miejsce | 3× PREVIEW z `seed=12345` | za każdym razem ten sam, jeden zwycięzca |
| **P12** `test_p12_schedule_change_after_submission_is_respected` | st: IO 100 (W01, L01) | `update_meeting(L01 → śr 8:30)`, close, FINAL | 0 przydziałów, powód „…kolidują ze sobą” (lab na wykładzie) |
| **P13** `test_p13_api_flow` | – | REST: POST rounds (PREFERENCES) → PUT preferences (40, 101, 0, 60) → POST enrollments → preview → GET allocation → FINAL przed/po close → raport → plan → audyt | 200 / 409 BUDGET_EXCEEDED / 422 / 200; 409 ROUND_CLOSED; PREVIEW ASSIGNED; 409 ROUND_NOT_CLOSED → 200 assigned=1; raport FINAL, 2 zgłoszenia; plan `source=ALLOCATION`; audyt `[]` |

---

## A – optymalizator przydziału (bez bazy, `app/domain/allocation.py`)

Każdy wynik `allocate()` w testach jest dodatkowo sprawdzany przez `verify()`: limity miejsc, kolizje
między przydziałami i z planem, wymagania, komplet typów zajęć, grupy tylko ze zgłoszenia.

| Test | Dane | Oczekiwany wynik |
|---|---|---|
| A1 `test_higher_weight_wins_contested_seat` | 1 miejsce; s1: waga 30, s2: waga 70 | s2 przydzielony, s1 `FULL`; suma 70, górne ograniczenie 100 |
| A2 `test_tie_is_decided_by_seeded_lottery_and_is_reproducible` | 8 osób, ta sama waga, 1 miejsce, ziarna 0..19 | różne ziarna → różni zwycięzcy; to samo ziarno → ten sam |
| A3 `test_group_rank_is_respected_when_seats_allow` | L10 (1 miejsce), L11 (5); obie osoby wolą L10 | waga 60 → L10 (u=60), waga 40 → L11 (u=36) |
| A4 `test_lecture_and_lab_all_or_nothing` | wykład 5 miejsc, lab 1 | jedna osoba dostaje wykład **i** lab; druga nic (`FULL`) – nie sam wykład |
| A5 `test_no_conflict_between_assigned_courses_of_one_student` | 2 przedmioty o tej samej porze, wagi 30/70 | przydzielony 70, drugi `OWN_CONFLICT` |
| A6 `test_existing_plan_prerequisites_and_already_enrolled` | plan PON 8 (K300 LAB), brak AM1 | `CONFLICT`, `PREREQUISITES`, `ALREADY_ENROLLED`; górne ograniczenie 0 |
| A7 `test_parity_groups_do_not_conflict` | ODD i EVEN o tej samej porze | oba przedmioty przydzielone |
| A8 `test_improvement_moves_flexible_student_to_second_choice` | s2 (60) akceptuje L10, L11; s1 (50) tylko L10 | zachłannie 60; z poprawą 104 (s2 → L11, s1 → L10) |
| A9 `test_improvement_evicts_own_less_valuable_course` | kolizja z własnym tańszym przydziałem | ważniejszy przedmiot przydzielony |
| A10 `test_quality_against_exact_optimum_on_random_instances` | 300 losowych instancji (3–5 studentów, 3 przedmioty, wykład+lab), optimum przeglądem zupełnym | ograniczenia zawsze spełnione; średnio ≥ 99% optimum; ≥ 93% instancji dokładnie optymalnych; lepiej niż sam zachłanny |
| A11 `test_scale_one_program_round_is_fast` | 1000 studentów × 6 przedmiotów, 30 przedmiotów × (wykład + 5 labów po 15) | < 30 s (zmierzone ok. 7 s), ≥ 90% miejsc w labach zajętych, `verify` OK |
| A12 `test_validate_preferences_*` (9 przypadków) | zgłoszenia z błędami | kody: `BUDGET_EXCEEDED`, `BAD_WEIGHT`, `BAD_SECTION` (×3), `DUPLICATE_SECTION`, `DUPLICATE_COURSE`, `NO_SECTIONS`; poprawne i puste → brak błędów |

### Zmierzona jakość optymalizatora (A10, 1000 instancji)

| Wariant | Średnio % optimum | Najgorszy przypadek | Instancje z dokładnym optimum |
|---|---|---|---|
| sam algorytm zachłanny (waga malejąco) | 98,1% | 55% | 83,9% |
| zachłanny + poprawa lokalna (wdrożony) | **99,8%** | 80% | **97,1%** |

Problem z kolizjami jest NP-trudny. Przegląd zupełny jest możliwy tylko dla małych instancji, dlatego
dla dużych raport podaje **górne ograniczenie** (sumę wag wykonalnych zgłoszeń) i stosunek wyniku do
niego (`allocation_run.total_utility / upper_bound`, raport dziekanatu UC33).
