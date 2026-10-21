# USOSv2 – implementacja

Działająca wersja systemu zapisów: backend (FastAPI + PostgreSQL 16), worker w tle,
frontend (React + TypeScript), środowisko Docker Compose i test obciążeniowy (k6).

Dokumenty etapu 2 (`README.md`, `schemat.sql`, slajdy) opisują projekt sprzed implementacji.
Aktualny schemat to [`backend/migrations/versions/0001_initial.sql`](backend/migrations/versions/0001_initial.sql);
różnice są w sekcji „Zmiany względem etapu 2”.

## Uruchomienie

```bash
docker compose up -d --build                         # baza, migracje, API, worker, nginx, Mailpit
docker compose run --rm api python -m app.seed       # dane demo (mock-up: IO, BD, TS…)
```

- aplikacja: http://localhost:8080 – konta `admin@uczelnia.pl`, `dr.zachara@uczelnia.pl`,
  `s400001@uczelnia.pl`, hasło `haslo123`,
- wysłane e-maile (Mailpit): http://localhost:8025,
- dokumentacja API (OpenAPI): http://localhost:8080/api/docs.

Dane w skali uczelni (20 kierunków × 1000 studentów, 600 kursów, 9000 grup, 180 tys. ocen, ok. 8 s):

```bash
docker compose run --rm api python -m app.seed --scale university [--open-all]
```

Na produkcji trzeba ustawić `USOS_JWT_SECRET` (bez tego API loguje ostrzeżenie).

### Praca lokalna

```bash
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head
uv run pytest                       # 35 testów, w tym współbieżne na prawdziwym PostgreSQL
uv run uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev     # http://localhost:5173, proxy /api -> :8000
```

Testy używają bazy `usos_test` w kontenerze `db` (`CREATE DATABASE usos_test` przy pierwszym uruchomieniu).

## Struktura

| Katalog | Zawartość |
|---|---|
| `backend/app/domain/` | **Reguły biznesowe** jako czyste funkcje: kolizje terminów, wymagania wstępne i cykle, reguły zapisu, tury. Bez bazy, testowane jednostkowo. |
| `backend/app/services/` | Transakcje: `enrollment` (zapis, wypis, lista oczekujących, awans), `catalog` (katalog i harmonogram z kolizjami sal i prowadzących), `rounds`, `users`, `records` (import ocen), `audit`, `queries` (odczyty dla UI), `loaders` (dostęp do danych dla reguł). |
| `backend/app/api/` | REST API: student, prowadzący, dziekanat; uwierzytelnianie JWT, role. |
| `backend/app/traffic.py` | Kontrola ruchu: cache katalogu, limit żądań, bramki współbieżności. |
| `backend/app/worker.py` | Tury według harmonogramu, wygaszanie list, wysyłka e-maili z outboxa, audyt co minutę. |
| `backend/tests/` | Domena, serwisy (wyścigi, zakleszczenia), API, worker. |
| `frontend/` | Panele studenta (katalog z powodami odmowy, plan tygodnia, listy, powiadomienia), prowadzącego (listy grup, CSV) i dziekanatu (tury, katalog, decyzje, import, audyt). |
| `loadtest/otwarcie_tury.js` | Test k6: otwarcie tury. |

## Logika biznesowa poza bazą

Decyzje zapadają w `app/domain`. Zapytania w `services` tylko czytają dane i zapisują wynik.
W bazie zostają:
- ograniczenia spójności: klucze, `UNIQUE`, `CHECK`, indeksy częściowe – siatka bezpieczeństwa,
- blokady (`FOR UPDATE`, `NOWAIT`, blokady doradcze przy kolizjach sal i cyklach wymagań) –
  poprawność przy współbieżności nie da się zapewnić w samej aplikacji.

Siatka bezpieczeństwa się przydała: przy przepisywaniu dostępu do danych błąd spowodował, że
blokada grupy przestała działać. Test wyścigu (30 osób, 10 miejsc) wykrył go od razu, bo
`CHECK (enrolled_count <= capacity)` odrzucił 11. zapis.

## Duży ruch

Założenie: 20 000 studentów, tury osobno dla kierunków (`round_program`), przesunięte w czasie –
w panelu dziekanatu jest „Rozłóż tury kierunków” (np. kolejny kierunek co 30 min).

Mechanizmy:
1. **Tury per kierunek** – szczyt to ok. 1000 osób zamiast 20 000.
2. **Krótkie blokady** – reguły zależne od planu studenta sprawdzane pod blokadą studenta,
   blokada popularnej grupy obejmuje tylko kilka zapytań na końcu.
3. **Kontrola wejścia** (`traffic.py`) – najwyżej N transakcji zapisu na proces; nadmiar dostaje
   szybko 503 z `Retry-After` zamiast trzymać połączenia. Limit operacji na studenta (429);
   odrzucenie przez bramkę nie zużywa limitu. Frontend sam ponawia z losowym rozrzutem.
4. **Cache odczytów** – katalog i szczegóły kursu (3 s, równoczesne chybienia czekają na jedno
   zapytanie), dane katalogowe grupy przy zapisie (10 s).
5. **Gorąca ścieżka bez ORM** – zapisy i odczyty dla reguł idą bezpośrednio przez asyncpg;
   profilowanie pokazało, że narzut budowania zapytań w SQLAlchemy był głównym kosztem CPU.
6. **Bezstanowe API** – skaluje się kolejnymi instancjami; statyka z nginx.
7. **Logowanie przed turą** – token JWT ważny 12 h, bcrypt o koszcie 10.

### Wyniki testu obciążeniowego

Jedna maszyna (16 rdzeni, WSL2 + Docker Desktop), wszystko razem z k6; 8 procesów API.
Każdy student: katalog, status grup i zapis na 6 przedmiotów (wykład + laboratorium, do 3 prób
laboratorium przy kolizji), potem plan.

| Scenariusz | Zapisów / odmów | p95 zapisu | Sesja studenta | Ponowienia (429/503) | Niezmienniki |
|---|---|---|---|---|---|
| 1 kierunek, 1000 osób – pierwsza wersja | 11 287 | 2,5 s + ponowienia do 19 s | 2 min | 22 873, 1576 nieudanych | OK |
| 1 kierunek, 1000 osób – po optymalizacjach | 10 671 | **1,92 s** | **17 s** | **0** | OK |
| 3 kierunki naraz, 3000 osób (przeciążenie) | 31 881 | 2,1 s + ponowienia | 49 s | 18 034, 163 nieudanych (0,5%) | OK, 0 przepełnień |

Wąskim gardłem jest CPU procesów API (baza pracuje na ok. 1/4 mocy), więc przepustowość rośnie
z liczbą instancji API. Trzy kierunki naraz to przeciążenie tej jednej maszyny – system zwalnia
i część żądań odsyła do ponowienia, ale nie traci spójności. Dlatego tury per kierunek.

Uruchomienie:

```bash
docker compose run --rm api python -m app.seed --scale university
docker run --rm --network usosv2_default -v "$PWD/loadtest:/s" grafana/k6:1.3.0 run \
    -e PROGRAMS=1 -e PER_PROGRAM=1000 /s/otwarcie_tury.js
```

## Zmiany względem etapu 2

- Jedna tabela `app_user` z rolą (zamiast `student` i `lecturer`); dane roli w kolumnach z `CHECK`.
- Tabela `program` (kierunek) i `round_program`: tura obejmuje wybrane kierunki, tury mogą się
  nakładać (usunięty indeks „jedna otwarta tura w semestrze”).
- Bez funkcji `schedule_conflicts`, `same_course_kind_section`, triggera cykli i widoku audytu –
  przeniesione do `app/domain` i `app/services/audit.py`.
- `enrollment.created_by` / `dropped_by` – kto wykonał operację (ślad dla dziekanatu i RODO).
- `notification.read_at`, `attempts` – powiadomienia w aplikacji i ponawianie wysyłki.

## Znane ograniczenia

- Limit żądań i cache są per proces (przy N instancjach limit jest przybliżony).
- Zmiana terminu grupy przez dziekanat w trakcie tury dociera do zapisów w innych procesach
  po najwyżej 10 s; nie weryfikuje też ponownie planów już zapisanych studentów.
- Kursy nie są przypisane do kierunków – tura ogranicza, kto i kiedy się zapisuje, nie na co.
- Logowanie hasłem; docelowo SSO uczelni.
