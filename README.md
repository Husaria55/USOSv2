# System zapisów na zajęcia – Krok 2: architektura, prototypy i struktury danych

Termin: **21.X** (prezentacja). Ocena z etapu: **30%** oceny z projektu.

Wymagania etapu (z opisu zadania):

> Zespół przedstawia proponowaną **architekturę** rozwiązania. Należy przygotować pierwsze
> **prototypy** dla obszarów, które potencjalnie mogą być najbardziej problematyczne
> (albo mock-upy UI). Należy opisać główne **przypadki użycia**. Kolejnym elementem jest
> **projekt struktury danych** (diagram ER: tabele, kolumny, typy, klucze).

Temat 2, *System zapisu na zajęcia*:

> Studenci zapisują się na zajęcia z ograniczoną liczbą miejsc, przedmiotów wstępnych
> i potencjalnie kolidujących harmonogramów. Obsługa katalogu: kursów, sekcji, wykładowców
> i harmonogramów. Wsparcie dla: różnych rozmiarów grup, wymagań wstępnych (zaliczonych
> przedmiotów), wykrywanie konfliktów w harmonogramie. Listy oczekujących z automatycznym
> zapisywaniem, gdy zwolni się miejsce.

### Gdzie które wymaganie jest pokryte

| Wymaganie z tematu | Przypadek użycia | Tabele (ER) | Prototyp |
|---|---|---|---|
| ograniczona liczba miejsc | UC2, UC13 | `section.capacity`, `enrolled_count`, `waitlist_limit` | scenariusz 1, 5 |
| katalog: kursy, sekcje, wykładowcy, harmonogramy | UC1, UC11, UC12 | `course`, `section`, `lecturer`, `section_lecturer`, `meeting`, `room`, `term` | – |
| różne rozmiary grup | UC12, UC13 | `section.capacity` per grupa, `section.kind`, `room.seats` | scenariusz 1, 4, 5 |
| wymagania wstępne (zaliczone przedmioty) | UC3, UC11, UC15 | `course_prerequisite`, `completed_course` | scenariusz 2 |
| wykrywanie konfliktów w harmonogramie | UC4, UC12 | `meeting` (dzień, godziny, parzystość tygodni) | scenariusz 3 |
| listy oczekujących z automatycznym zapisem | UC5, UC7, UC9 | `waitlist_entry`, `notification` | scenariusz 4 |

## Zawartość folderu

| Plik | Co to jest |
|---|---|
| `diagramy/architektura.puml` / `.png` | Diagram architektury (moduły i połączenia) |
| `diagramy/przypadki_uzycia_student.puml` / `.png` | Przypadki użycia 1/2: student i zapisy |
| `diagramy/przypadki_uzycia_administracja.puml` / `.png` | Przypadki użycia 2/2: dziekanat, prowadzący, zegar |
| `diagramy/er.puml` / `.png` | Diagram ER bazy danych |
| `schemat.sql` | Schemat bazy dla PostgreSQL 16 (tabele, ograniczenia, funkcja wykrywania kolizji) |
| `prototyp/prototyp_zapisow.py` | Działający prototyp najbardziej ryzykownych mechanizmów |
| `mockup/mockup.html` / `.png` | Mock-up ekranu zapisów studenta |

Pliki `.puml` to źródła w PlantUML, a `.png` to wersje gotowe do slajdów (instrukcja regeneracji
na końcu).

---

## 1. Architektura

![architektura](diagramy/architektura.png)

System to aplikacja webowa w trzech warstwach plus osobny proces w tle:

- **Warstwa prezentacji** – aplikacja SPA (React + TypeScript) dla trzech ról: student,
  prowadzący, administrator (dziekanat).
- **Backend (FastAPI)** – REST API oraz moduły:
  - `CatalogService` – kursy, wymagania wstępne, grupy, sale, prowadzący, terminy zajęć,
    tury zapisów,
  - `EnrollmentService` – zapisy i wypisy. Jedyny moduł, który zmienia liczbę zajętych miejsc,
  - `PrerequisiteChecker` – sprawdza, czy student zaliczył wymagane przedmioty,
  - `ScheduleConflictDetector` – kolizje w planie studenta, a przy układaniu harmonogramu
    także kolizje sal i prowadzących,
  - `WaitlistService` – kolejka oczekujących i automatyczny zapis po zwolnieniu miejsca,
  - `NotificationService` – zapisuje powiadomienia do tabeli-outboxa.
- **Worker w tle** – otwiera i zamyka tury zapisów o zadanych godzinach oraz wysyła e-maile
  z outboxa przez serwer SMTP. Wysyłka jest poza transakcją zapisu, więc wolny serwer pocztowy
  nie blokuje zapisów.
- **PostgreSQL** – jedno źródło prawdy. O liczbie miejsc i kolejności na liście decydują
  transakcje i blokada wiersza grupy (`SELECT ... FOR UPDATE`).

**Główne wyzwanie architektoniczne** to szczyt obciążenia w chwili otwarcia tury: setki
studentów jednocześnie próbują zająć te same miejsca. Dlatego zapis do jednej grupy jest
serializowany blokadą jej wiersza, a zapisy jednego studenta blokadą wiersza studenta.
Zapisy różnych studentów do różnych grup idą równolegle. API ma limit
żądań na użytkownika.

### Stos technologiczny (wstępny)

| Element | Technologia | Uzasadnienie |
|---|---|---|
| Frontend | React + TypeScript | Popularny, typowany, łatwo zbudować katalog, formularze i siatkę planu |
| Backend | Python 3.12 + FastAPI + SQLAlchemy | Szybkie prototypowanie, automatyczna dokumentacja OpenAPI, walidacja przez Pydantic, obsługa wielu równoczesnych żądań (async) |
| Baza danych | PostgreSQL 16 | Transakcje ACID, blokady wierszy, indeksy częściowe (`UNIQUE ... WHERE`), typy `TIME` i `JSONB` |
| Zadania w tle | Własny worker (APScheduler) | Outbox i tury zapisów są w bazie, więc osobny broker (Redis/RabbitMQ) nie jest potrzebny |
| Uwierzytelnianie | JWT; docelowo SSO uczelni | Bezstanowe API, łatwe rozdzielenie ról |
| Wdrożenie | Docker Compose (frontend, api, worker, db) | Jednakowe środowisko dla całego zespołu |

---

## 2. Przypadki użycia

Diagram podzielono na dwa, żeby był czytelny.

![przypadki użycia – student](diagramy/przypadki_uzycia_student.png)

![przypadki użycia – administracja](diagramy/przypadki_uzycia_administracja.png)

**Aktorzy:** Student, Prowadzący, Administrator (dziekanat), Zegar systemowy.

Notacja jest wzorowana na przykładzie bankomatu z
[uml-diagrams.org](https://www.uml-diagrams.org/bank-atm-uml-use-case-diagram-example.html):

- asocjacja aktor–przypadek to zwykła linia, bez strzałki,
- *Operacja studenta* i *Operacja pracownika* (kursywa) to **abstrakcyjne** przypadki użycia.
  Konkretne operacje je uogólniają (strzałka z pustym grotem), a każda z nich przez
  `<<include>>` wymaga **UC0: Uwierzytelnij się**,
- `<<include>>` – zachowanie zawsze wykonywane (zapis zawsze sprawdza wymagania i kolizje),
- `<<extend>>` – zachowanie opcjonalne w nazwanym punkcie rozszerzenia: UC5 (lista
  oczekujących) rozszerza UC2 w punkcie „brak wolnych miejsc”.

### Główne scenariusze

**UC2 – Zapisz się do grupy** (Student)
- Warunki wstępne: student jest zalogowany, tura zapisów jest otwarta.
- Przebieg:
  1. Student wybiera grupę z katalogu (UC1).
  2. System blokuje wiersz grupy (żeby inne zapisy do tej grupy czekały).
  3. System sprawdza wymagania wstępne (UC3): wszystkie przedmioty wymagane przez kurs muszą być zaliczone.
  4. System sprawdza kolizje (UC4) z grupami, do których student jest już zapisany.
  5. Jeśli są wolne miejsca, system zapisuje studenta i zwiększa licznik zajętych miejsc.
  6. Student widzi grupę w swoim planie (UC8).
- Scenariusze alternatywne:
  - brak zaliczenia albo kolizja → odmowa z podaniem przyczyny (który przedmiot, z jaką grupą);
  - student jest już zapisany do innej grupy **tego samego przedmiotu i typu** (np. drugie
    laboratorium z IO) → odmowa. Wykład i laboratorium z jednego przedmiotu są dozwolone;
  - brak miejsc → **UC5**: student zostaje dopisany na koniec listy oczekujących (o ile lista
    nie przekroczyła `waitlist_limit`) i widzi swoją pozycję;
  - student jest już zapisany lub już czeka → odmowa (indeksy `UNIQUE ... WHERE`).

**UC6 – Wypisz się z grupy** (Student) – obejmuje **UC9**
- W jednej transakcji: zapis zmienia status na DROPPED, licznik miejsc maleje i od razu
  uruchamia się UC9.

**UC9 – Awansuj pierwszego z listy oczekujących** (system)
- Wywoływany po zwolnieniu miejsca (UC6, UC14) albo zwiększeniu limitu (UC13).
- System bierze oczekujących w kolejności dopisania i dla każdego **ponownie** sprawdza
  wymagania, kolizje i regułę „jedna grupa danego typu na przedmiot”. Od chwili dopisania do listy student mógł zapisać się na zajęcia
  w tym samym terminie.
  - spełnia warunki → zostaje zapisany (`source = WAITLIST`) i dostaje powiadomienie;
  - nie spełnia → wpis dostaje status SKIPPED z powodem, student dostaje powiadomienie,
    system bierze następną osobę.
- Kończy się, gdy zabraknie miejsc albo lista się wyczerpie. Niezmiennik: **nikt nie czeka
  na liście, gdy w grupie są wolne miejsca.**

**UC7 – Zrezygnuj z listy oczekujących** (Student) – wpis dostaje status CANCELLED, a kolejni
przesuwają się w górę.

**UC10 – Przeglądaj listy studentów swoich grup** (Prowadzący) – lista zapisanych i oczekujących.

**UC11 / UC12 – Katalog i harmonogram** (Administrator)
- Kursy z wymaganiami wstępnymi. Grupy różnego typu i rozmiaru (wykład 150, ćwiczenia 30,
  laboratorium 15), przypisanie prowadzących, terminy (dzień, godziny, tygodnie
  parzyste/nieparzyste) i sale.
- Przy dodawaniu terminu system wykrywa kolizje sal i prowadzących (UC4), a limit grupy nie
  może przekraczać liczby miejsc w sali.

**UC13 – Zmień limit miejsc** (Administrator) – przy zwiększeniu limitu od razu uruchamia się
UC9. Zmniejszyć limit można najwyżej do liczby zapisanych osób.

**UC14 – Zapisz / wypisz studenta** (Administrator) – decyzja dziekanatu (`source = ADMIN`),
np. powtarzanie przedmiotu. Wypis uruchamia UC9.

**UC15 – Importuj zaliczone przedmioty** (Administrator) – oceny z poprzednich semestrów
(np. eksport z systemu ocen), na których opiera się UC3.

**UC16 – Otwórz / zamknij turę zapisów** (Zegar systemowy lub Administrator) – zapisy
i wypisy są możliwe tylko w otwartej turze.

---

## 3. Struktury danych (diagram ER)

![ER](diagramy/er.png)

Pełna definicja tabel, typów, kluczy i ograniczeń: [`schemat.sql`](schemat.sql) (sprawdzone
na PostgreSQL 16).

### Najważniejsze decyzje projektowe

1. **Kurs ≠ grupa.** `course` to przedmiot w katalogu (kod, ECTS, wymagania). `section` to
   konkretna grupa w danym semestrze (`term`): typ, własny limit miejsc, prowadzący.
   Dzięki temu jeden kurs może mieć wykład na 150 osób i kilka laboratoriów po 15.
2. **Harmonogram jako osobna tabela `meeting`.** Grupa może mieć kilka terminów w tygodniu.
   Termin to dzień tygodnia, godziny od–do, parzystość tygodni (`ALL | ODD | EVEN`) i sala.
3. **Reguła kolizji.** Dwa terminy kolidują, gdy są tego samego dnia, godziny się przecinają
   (`start1 < end2 AND start2 < end1`, więc zajęcia 8:00–9:30 i 9:30–11:00 **nie** kolidują),
   a tygodnie się pokrywają (ALL koliduje ze wszystkim, ODD tylko z ODD, EVEN tylko z EVEN).
   W schemacie jest gotowa funkcja SQL `schedule_conflicts(student, grupa)`.
4. **Wymagania wstępne** to tabela łącznikowa kurs → kurs wymagany. Zaliczenia są w
   `completed_course` (z oceną i semestrem, bo przedmiot można powtarzać).
5. **`section.enrolled_count` jako licznik.** Dałoby się go liczyć z `enrollment`, ale
   trzymamy go w grupie, żeby sprawdzenie limitu i zajęcie miejsca było jednym warunkowym
   `UPDATE`. Dodatkowo `CHECK (enrolled_count <= capacity)` blokuje overbooking nawet przy
   błędzie w kodzie.
6. **Historia zamiast kasowania.** Wypis zmienia status na `DROPPED`, a wpis na liście
   status na `PROMOTED / SKIPPED / CANCELLED`. Indeksy częściowe
   (`UNIQUE (student, grupa) WHERE status = 'ENROLLED'` / `'WAITING'`) pozwalają na wiele
   historycznych wpisów, ale tylko jeden aktywny.
7. **Kolejność na liście oczekujących** wyznaczają `created_at` i `id`, bez osobnej kolumny
   „pozycja”. Rezygnacja nie wymaga więc przenumerowania pozostałych.
8. **Outbox powiadomień.** `notification` zapisuje się w tej samej transakcji co awans
   z listy, a worker wysyła e-maile później. Powiadomienie nie zginie i nie zostanie wysłane
   dla awansu, który się wycofał.

---

## 4. Prototypy obszarów problematycznych

Za najbardziej ryzykowne uznaliśmy:

1. **Wyścig o ostatnie miejsca** w chwili otwarcia zapisów. To klasyczny błąd *check-then-act*:
   wielu studentów odczytuje „zostało 1 miejsce” i wszyscy się zapisują.
2. **Wymagania wstępne.**
3. **Wykrywanie kolizji** – łatwo pomylić się przy zajęciach stykających się końcem
   i początkiem oraz przy tygodniach parzystych i nieparzystych.
4. **Automatyczny zapis z listy oczekujących:**
   - każde zwolnione miejsce zajęte dokładnie raz, także przy równoczesnych wypisach,
   - zachowana kolejność listy,
   - pominięcie osób, które w międzyczasie przestały spełniać warunki.

Prototyp [`prototyp/prototyp_zapisow.py`](prototyp/prototyp_zapisow.py) sprawdza wszystkie
cztery obszary na równoległych wątkach i bazie SQLite (tylko biblioteka standardowa Pythona,
nic nie trzeba instalować):

```bash
cd prototyp
python3 prototyp_zapisow.py
```

Wynik:

```
== 1. Otwarcie zapisów: 30 studentów jednocześnie, grupa na 10 miejsc ==
[naiwny ] zapisanych: 30 / 10 miejsc, licznik w grupie: 1
    -> wersja naiwna zapisała więcej osób niż jest miejsc (overbooking)
[bezpieczny] zapisanych: 10 / 10 miejsc, licznik w grupie: 10
    -> 10 zapisanych, 20 na liście oczekujących, niezmienniki OK

== 2. Wymagania wstępne ==
    Ania (zaliczyła AM1):     ENROLLED
    Bartek (nie zaliczył AM1): odrzucono - brak zaliczenia: AM1

== 3. Wykrywanie kolizji w planie ==
    plan studenta: pon 10:00-11:30, śr 12:00-13:30 (tyg. nieparzyste)
    pon 11:00-12:30 (nachodzi)             -> KOLIZJA
    pon 11:30-13:00 (styka się końcem)     -> ok
    wt  10:00-11:30 (inny dzień)           -> ok
    śr  12:00-13:30 tyg. parzyste          -> ok
    śr  13:00-14:30 co tydzień             -> KOLIZJA

== 4. Lista oczekujących ==
    grupa L01 pełna (2/2), oczekują kolejno: 3, 4, 5, 6
    student 3 zapisał się tymczasem na BD L05 (kolizja z L01)
    student 1 wypisuje się -> [(3, 'SKIPPED (kolizja z: L05)'), (4, 'PROMOTED')]
    dziekanat zwiększa limit do 3 -> [(5, 'PROMOTED')]
    dwóch zapisanych wypisuje się w tej samej chwili:
    -> awansowani: [6, 7] (pierwsi dwaj z listy: [6, 7])
    -> każde zwolnione miejsce zajęte dokładnie raz, kolejność listy zachowana
    powiadomienia (outbox):
      3: SKIPPED  Nie zapisano z listy oczekujących: kolizja z: L05
      4: PROMOTED Zwolniło się miejsce - zostałeś zapisany.
      5: PROMOTED Zwolniło się miejsce - zostałeś zapisany.
      6: PROMOTED Zwolniło się miejsce - zostałeś zapisany.
      7: PROMOTED Zwolniło się miejsce - zostałeś zapisany.

== 5. Jedna grupa danego typu na przedmiot, limit listy oczekujących ==
    Piotr do pełnej L03:          WAITLISTED
    Kuba do pełnej L03:           odrzucono - grupa 2: brak miejsc i pełna lista oczekujących
    Piotr na wykład W01:          ENROLLED  (inny typ zajęć - wolno)
    Piotr do L05 (czeka na L03):  ENROLLED
    Piotr ponownie do L03:        odrzucono - już zapisany do grupy L05 tego przedmiotu
    Ola wypisuje się z L03 ->     [(2, 'SKIPPED (już zapisany do grupy L05 tego przedmiotu)')]
    -> Piotr nie dostał drugiego laboratorium z IO; L03 ma wolne miejsce i pustą listę

Wszystkie niezmienniki spełnione.
```

Dokładne liczby w wersji naiwnej zależą od kolejności wątków i mogą się różnić między
uruchomieniami. Wersja bezpieczna zawsze daje ten sam wynik.

### Wnioski z prototypu

- Sprawdzenie limitu i zajęcie miejsca muszą być **jedną atomową operacją**:
  `UPDATE section SET enrolled_count = enrolled_count + 1 WHERE id = ? AND enrolled_count < capacity`.
  Gdy zmieni się 0 wierszy, nie ma miejsc i student trafia na listę oczekujących.
- Awans z listy musi się dziać **w tej samej transakcji** co zwolnienie miejsca. Inaczej
  w chwili między wypisem a awansem ktoś spoza listy może „przeskoczyć kolejkę”.
- Przy awansie trzeba **ponownie** sprawdzić wymagania i kolizje, bo od dopisania do listy
  plan studenta mógł się zmienić. Pominiętych oznaczamy (SKIPPED) i informujemy, zamiast
  ich po cichu usuwać.
- **Blokada studenta, nie tylko grupy.** Reguły kolizji i „jednej grupy danego typu” dotyczą
  całego planu studenta. Jeśli student naraz wyśle zapisy do dwóch różnych grup (np. dwie
  karty przeglądarki), blokada samego wiersza grupy nie wystarczy: obie transakcje sprawdzą
  plan, zanim którakolwiek go zmieni. W PostgreSQL zapis blokuje więc **najpierw wiersz
  studenta, potem wiersz grupy** (zawsze w tej kolejności, żeby uniknąć zakleszczeń).
  W prototypie SQLite problem nie występuje, bo `BEGIN IMMEDIATE` blokuje całą bazę.
- Funkcja `check_invariants` przyda się później jako test regresyjny i okresowy audyt:
  - licznik w grupie = liczba zapisanych,
  - limit nieprzekroczony,
  - nikt nie czeka, gdy są wolne miejsca,
  - nikt nie jest jednocześnie zapisany i oczekujący.
- **Ograniczenie prototypu:** `BEGIN IMMEDIATE` w SQLite blokuje całą bazę, a nie jeden wiersz
  grupy. Prototyp potwierdza zasadę działania, ale nie wydajność ani blokowanie per grupa
  w PostgreSQL. To sprawdzimy w kolejnym etapie. Sam `schemat.sql` jest sprawdzony na
  PostgreSQL 16:
  - `CHECK` blokuje overbooking,
  - indeks częściowy blokuje podwójny zapis,
  - `schedule_conflicts` poprawnie odróżnia kolizję od zajęć stykających się końcem.

---

## 5. Mock-up interfejsu

![mockup](mockup/mockup.png)

[`mockup/mockup.html`](mockup/mockup.html) – statyczny prototyp ekranu zapisów studenta
(wystarczy otworzyć w przeglądarce). Pokazuje:
- katalog kursów z grupami i zajętością miejsc,
- informację o wymaganiach wstępnych (kurs ZIO zablokowany, bo IO niezaliczone),
- przycisk zapisu zablokowany przez kolizję z podaniem, z którą grupą,
- pozycję na liście oczekujących i przycisk „Dołącz do listy” dla pełnej grupy,
- tygodniową siatkę planu z zajęciami co dwa tygodnie,
- powiadomienia o automatycznym zapisie i o pominięciu na liście.

---

## Regeneracja diagramów

```bash
# jednorazowo: pobranie PlantUML (wymaga Javy)
curl -L -o plantuml.jar https://repo1.maven.org/maven2/net/sourceforge/plantuml/plantuml/1.2025.4/plantuml-1.2025.4.jar
java -jar plantuml.jar -tpng diagramy/*.puml
```

Diagramy używają `!pragma layout smetana`, więc Graphviz nie jest potrzebny. Pliki `.puml`
można też wkleić na https://www.plantuml.com/plantuml.

## Co zostaje na krok 3 (projekt wstępny, 28.X)

- diagramy sekwencji (zapis do grupy, wypis z awansem z listy, otwarcie tury),
- diagram klas/komponentów z metodami, parametrami i zwracanymi wartościami,
- przypadki użycia rozpisane dla wszystkich wymagań, w tym uprawnienia ról i obsługa błędów.
