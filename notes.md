# Notatki: pytania i odpowiedzi

## Pytanie 1: Co każdy scenariusz testuje?

Chodzi o 6 scenariuszy ryzyka z prototypu (`prototyp/prototyp_zapisow.py`). Po każdym wywoływane jest `check_invariants()`.

| # | Scenariusz | Co testuje |
|---|------------|-----------|
| 1 | Otwarcie zapisów: 30 studentów jednocześnie, grupa na 10 miejsc | Wyścig o ostatnie miejsca. Wersja naiwna (`naive_enroll`: odczyt licznika, potem osobny zapis) zapisuje ponad limit (overbooking), a licznik jest zaniżony, więc `CHECK` tego nie wykrywa. Wersja bezpieczna (jeden atomowy `UPDATE ... WHERE enrolled_count < capacity`) daje 10 zapisanych i 20 na liście oczekujących. |
| 2 | Wymagania wstępne | Student z zaliczonym AM1 (ocena 4.5) zapisuje się na AM2. Student z oceną 2.0 jest odrzucany (`MissingPrerequisite`). |
| 3 | Wykrywanie kolizji w planie | `find_conflicts` na 5 przypadkach: nakładanie godzin (kolizja), styk końcem i początkiem (brak), inny dzień (brak), tygodnie parzyste i nieparzyste (brak), ten sam termin co tydzień (kolizja). |
| 4 | Lista oczekujących | Awans po wypisie lub zwiększeniu limitu. Brak wolnego miejsca oznacza, że nikt nie awansuje. Osoba z kolizją w planie jest pomijana (`SKIPPED`). Dwa równoczesne wypisy awansują dokładnie dwóch pierwszych z listy z zachowaniem kolejności. Zmiana limitu (UC13) i powiadomienia (outbox). |
| 5 | Jedna grupa danego typu na przedmiot, limit listy, ponowny zapis | Ponowny zapis do tej samej grupy jest odrzucany (`AlreadyInSection`). Przy pełnej liście oczekujących jest odmowa (`SectionFull`). Wykład i laboratorium tego samego przedmiotu są dozwolone (inny typ). Zapis do innego laboratorium anuluje wpis na liście poprzedniego i zwalnia miejsce na liście. Pozostałe odmowy: `AlreadyInCourse`. |
| 6 | Decyzje dziekanatu i zamknięcie tury | Zapis przez dziekanat poza limitem i bez wymagań wstępnych (limit +1, a oczekujący nadal czeka). Zamknięcie tury sprawia, że listy wygasają (`EXPIRED`). Student nie może się wypisać po turze (`RoundClosed`). Wypis przez dziekanat po turze nikogo nie awansuje. |

Wspólny cel: pokazać, że najbardziej ryzykowne elementy (współbieżność, reguły zapisu, lista oczekujących, wyjątki dziekanatu) działają poprawnie i nie łamią niezmienników (licznik zgodny z liczbą zapisów, brak przekroczenia limitu, każde miejsce zajęte dokładnie raz).

## Pytanie 2: Czym jest licznik?

Licznik to kolumna `section.enrolled_count`: liczba studentów aktualnie zapisanych (`ENROLLED`) do danej grupy. Jest zdenormalizowaną kopią wyniku `COUNT(*)` z tabeli `enrollment`, trzymaną w grupie, żeby nie liczyć zapisów przy każdej próbie zapisu.

- **Do czego służy:** sprawdza, czy w grupie jest wolne miejsce (`enrolled_count < capacity`). Bezpieczny zapis robi to w jednym atomowym `UPDATE section SET enrolled_count = enrolled_count + 1 WHERE id = :section AND enrolled_count < capacity`. Jeśli `UPDATE` zmieni 0 wierszy, grupa jest pełna i student trafia na listę oczekujących.
- **Ograniczenie:** `CHECK (enrolled_count <= capacity)` pilnuje tylko samej wartości licznika, a nie tego, czy zgadza się on z rzeczywistą liczbą wierszy w `enrollment`.
- **Gdzie widać problem:** w scenariuszu 1 wersja naiwna (odczyt licznika, potem osobny zapis) zapisuje 30 osób do grupy na 10 miejsc, a licznik pokazuje 1. `CHECK` tego nie wykrywa. Wykrywa to widok `section_invariant_violations` oraz `check_invariants()`.
- **Niezmiennik:** licznik musi zawsze być równy liczbie zapisów ze statusem `ENROLLED` w grupie i nie może przekraczać `capacity`. Wyjątkiem jest zapis przez dziekanat ponad limit, który podnosi także `capacity`.

## Pytanie 3: Co znaczy każda tabela i co przechowuje?

Źródło: `schemat.sql` (PostgreSQL 16). Tabele pogrupowane tematycznie.

### Użytkownicy
| Tabela | Znaczenie | Co przechowuje |
|--------|-----------|----------------|
| `app_user` | Konto w systemie (jedna tabela dla wszystkich ról) | e-mail (unikalny), hash hasła, imię i nazwisko, rola (`STUDENT` / `LECTURER` / `ADMIN`), data utworzenia. Dla studenta: numer indeksu (unikalny), program (kierunek), semestr (1-12). Dla wykładowcy: tytuł, katedra/jednostka. CHECK-i pilnują, że kolumny danej roli są wypełnione tylko dla niej |

### Katalog
| Tabela | Znaczenie | Co przechowuje |
|--------|-----------|----------------|
| `course` | Przedmiot (kurs) | kod (unikalny), nazwa, punkty ECTS, opis |
| `course_prerequisite` | Wymagania wstępne | pary (kurs, kurs wymagany). Trigger `prevent_prerequisite_cycle` blokuje cykle, np. A wymaga B, a B wymaga A |
| `term` | Semestr | kod (np. `2026Z`), data początku i końca. Od daty początku liczone są tygodnie parzyste i nieparzyste |
| `enrollment_round` | Tura zapisów w semestrze | semestr, nazwa, `opens_at` / `closes_at` (harmonogram dla workera), status `PLANNED` / `OPEN` / `CLOSED`. W semestrze najwyżej jedna tura jest `OPEN` |
| `room` | Sala | budynek, numer, liczba miejsc |
| `section` | Grupa zajęciowa | kurs, semestr, kod (np. `W01`, `L12`), typ (`LECTURE` / `EXERCISE` / `LAB` / `SEMINAR`), `capacity` (limit), `enrolled_count` (licznik zapisanych), `waitlist_limit` (maks. długość listy oczekujących, domyślnie 50) |
| `section_lecturer` | Powiązanie grupa-wykładowca (wiele do wielu) | pary (grupa, wykładowca) |
| `meeting` | Termin cotygodniowy grupy (grupa może mieć kilka) | grupa, sala, dzień tygodnia, godzina początku i końca, parzystość tygodni (`ALL` / `ODD` / `EVEN`) |

### Historia studiów
| Tabela | Znaczenie | Co przechowuje |
|--------|-----------|----------------|
| `completed_course` | Zaliczone (lub niezaliczone) przedmioty studenta | student, kurs, semestr, ocena (2.0-5.0), `passed` (wyliczane automatycznie: ocena >= 3.0). Podstawa sprawdzania wymagań wstępnych |

### Zapisy
| Tabela | Znaczenie | Co przechowuje |
|--------|-----------|----------------|
| `enrollment` | Zapis studenta do grupy (także historia wypisów) | student, grupa, status (`ENROLLED` / `DROPPED`), źródło (`DIRECT` / `WAITLIST` / `ADMIN`), daty zapisu i wypisu. Unikalny indeks: tylko jeden aktywny zapis studenta w danej grupie |
| `waitlist_entry` | Wpis na liście oczekujących | student, grupa, status (`WAITING` / `PROMOTED` / `SKIPPED` / `CANCELLED` / `EXPIRED`), daty, powód pominięcia (`skip_reason`), powiązany zapis po awansie (`enrollment_id`). Kolejność na liście wyznacza `id` |
| `notification` | Outbox powiadomień | użytkownik, typ (`PROMOTED`, `SKIPPED`, `CANCELLED`, `EXPIRED`...), treść w JSON, daty utworzenia i wysyłki. Zapisywane w tej samej transakcji co zmiana, a wysyła je worker |

### Poza tabelami (w tym samym pliku)
- `schedule_conflicts` i `same_course_kind_section`: funkcje sprawdzające kolizje w planie i regułę "jedna grupa danego typu na przedmiot w semestrze".
- Widok `section_invariant_violations`: audyt niezmienników, m.in. czy licznik zgadza się z liczbą zapisów. Pusty wynik oznacza, że wszystko jest w porządku.

## Pytanie 4: Jak łączą się te tabele?

Relacje wynikają z kluczy obcych w `schemat.sql` (diagram: `diagramy/er.pdf`, źródło `diagramy/er.py`).

### Użytkownicy
- `notification.user_id` → `app_user.id` (użytkownik ma wiele powiadomień)
- Wszystkie odwołania do studenta i wykładowcy (`student_id`, `lecturer_id`) wskazują na `app_user.id`. Klucz obcy nie sprawdza roli: przy zapisie robi to blokada `SELECT ... FROM app_user WHERE id = :s AND role = 'STUDENT' FOR UPDATE`, a przy przypisaniu prowadzącego `CatalogService`.

### Katalog
- `course_prerequisite.course_id` → `course.id` oraz `course_prerequisite.required_course_id` → `course.id`: relacja wiele do wielu kursu z samym sobą (kurs wymaga innych kursów).
- `enrollment_round.term_id` → `term.id` (semestr ma wiele tur).
- `section.course_id` → `course.id` (kurs ma wiele grup).
- `section.term_id` → `term.id` (grupa należy do semestru).
- `section_lecturer` → `section.id` i `app_user.id` (wykładowca): tabela łącząca, relacja wiele do wielu (grupa ma wielu wykładowców, wykładowca prowadzi wiele grup).
- `meeting.section_id` → `section.id` (grupa ma wiele terminów).
- `meeting.room_id` → `room.id` (termin odbywa się w sali). Sala jest przypisana do terminu, nie do grupy.

### Historia studiów
- `completed_course.student_id` → `app_user.id`
- `completed_course.course_id` → `course.id`
- `completed_course.term_id` → `term.id`

Student ma wiele zaliczeń (klucz główny: student + kurs + semestr).

### Zapisy
- `enrollment.student_id` → `app_user.id` oraz `enrollment.section_id` → `section.id`: relacja wiele do wielu student-grupa, z historią (status, źródło, daty).
- `waitlist_entry.student_id` → `app_user.id` oraz `waitlist_entry.section_id` → `section.id`: jak wyżej, ale dla listy oczekujących.
- `waitlist_entry.enrollment_id` → `enrollment.id` (unikalne, tylko dla statusu `PROMOTED`): łączy wpis na liście z zapisem utworzonym przy awansie.

### Skrót
```
app_user ─┬─ enrollment ─────── section ─┬─ course ─ course_prerequisite (samopowiązanie)
          ├─ waitlist_entry ─── section  ├─ term ─ enrollment_round
          ├─ completed_course            ├─ meeting ─ room
          ├─ section_lecturer ─ section  └─ section_lecturer
          └─ notification
```
`section` jest centralną tabelą: łączy katalog (kurs, semestr, wykładowcy, terminy) z zapisami (`enrollment`, `waitlist_entry`).

### Powiązania logiczne bez klucza obcego
`schedule_conflicts` łączy `enrollment` → `section` → `meeting` (terminy już zapisanych grup z terminami nowej grupy). `same_course_kind_section` łączy `enrollment` → `section` (ten sam kurs, typ i semestr). Wymagania wstępne sprawdza się przez `course_prerequisite` i `completed_course.passed`.
