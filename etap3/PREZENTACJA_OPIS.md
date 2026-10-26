# Etap 3 (28.X) – opis prezentacji i przygotowanie do pytań

Dwie wersje slajdów:
- **`prezentacja/prezentacja_krotka.pdf` – na prezentację (7 minut)**: tytuł, 10 slajdów treści
  i „Dziękujemy”, potem 12 slajdów zapasowych (pozostałe diagramy i ekrany – tylko przy pytaniach).
- `prezentacja/prezentacja.pdf` – pełna (26 slajdów treści, 35 stron z tytułem i stronami sekcji,
  ok. 15 min) – do oddania / przeglądania.

Kompilacja: `prezentacja/build.sh` w katalogu głównym raz pobiera tectonic do `.tools/bin`, potem
`cd etap3/prezentacja && ../../.tools/bin/tectonic prezentacja_krotka.tex` (i `prezentacja.tex`).
Szczegóły do każdego slajdu są w `README.md` (numery sekcji w nawiasach).

## Wersja 7 minut – skrypt

**Tekst do powiedzenia, czasy, podział na osoby i źródła liczb: [`SKRYPT_7MIN.md`](SKRYPT_7MIN.md)**
(jedyne źródło – nie kopiować go tutaj, żeby wersje się nie rozjechały).

**Zasada:** w 7 minut omawiamy jeden wątek od początku do końca – **zapis do grupy**: przypadek
użycia → sekwencja → klasy → dane – a pozostałe elementy projektu pokazujemy jednym slajdem
każdy: pięć pozostałych sekwencji (slajd 6), uprawnienia i błędy (slajd 9), weryfikację (slajd 10).
Pełne diagramy czekają w slajdach zapasowych.

**Przy pytaniach** – slajdy zapasowe w tej kolejności: przypadki dziekanatu, pełna sekwencja
zapisu, pełny wypis z awansem, tury i worker, dziekanat, harmonogram, wymagania + import,
logowanie, klasy (domena, serwisy, infrastruktura), ekrany.

**Notacja ramek na diagramach sekwencji** (może paść pytanie): `break` – błąd kończy operację
(wyjątek → `ROLLBACK` → odpowiedź z kodem), dalsze kroki się nie wykonują; `alt` – wybór jednej
z gałęzi; `opt` – krok warunkowy, po którym przebieg idzie dalej; `loop` – powtarzanie; `group` –
nazwany scenariusz (np. trzy decyzje dziekanatu na jednym diagramie). Przy awansie konflikt blokady
(55P03) to `alt`, bo `break` w pętli wychodziłby tylko z pętli, a przerywana jest cała transakcja.

## Pełna wersja – przebieg

| Slajd | Co powiedzieć (najważniejsze) |
|---|---|
| Co jest w etapie 3 | Zakres z opisu zadania. Projekt jest sprawdzony działającą implementacją – diagramy klas i sekwencji opisują istniejący kod. Trzy główne zmiany: tury per kierunek, reguły w kodzie zamiast SQL, jedna tabela użytkowników. (§1) |
| Architektura (diagram) | Przejść od góry: SPA → nginx (statyka, proxy) → API (HTTP, kontrola ruchu, serwisy, domena, dostęp do danych) → PostgreSQL; obok worker i SMTP. (§2) |
| Architektura: zasady | Domena nie zna bazy; serwis = transakcja; baza = siatka bezpieczeństwa. Historia z refaktoryzacji: błąd zdjął blokadę, `CHECK` odrzucił 11. zapis na 10 miejsc, test go złapał. |
| Stos technologiczny | Podkreślić uzasadnienia oparte na pomiarach: asyncpg w gorącej ścieżce, bo profilowanie pokazało koszt ORM; JWT 12 h, bo logowanie przed turą. (§3) |
| Przypadki użycia ×2 | Nowe: UC19 (status grup), UC20 (termin tury), UC22 (uprawnienie – tura kierunku), UC23 (rozłożenie tur), UC24–UC27. Notacja bez zmian. (§4) |
| Endpointy i błędy | Każdy UC ma endpoint i listę kodów błędów; pełna tabela w README. |
| Uprawnienia, błędy | Student nigdy nie podaje `student_id`. 409 z powodem po polsku; 429/503 ponawia SPA; deadlocki ponawia transakcja. (§8, §9) |
| Sekwencja: zapis | Kolejność: limit → bramka → blokada studenta → reguły planu → blokada grupy → miejsce. Dlaczego tak: popularna grupa zablokowana krótko. |
| Sekwencja: wypis + awans | Jedna transakcja; `NOWAIT` na studencie B; przy zajętym B wycofanie i ponowienie – B nie traci kolejki. SKIPPED z powodem. |
| Sekwencja: tura | Worker co 5 s; `scheduled_transition`; zamknięcie wygasza listy tylko kierunków bez otwartej tury; spóźnione wpisy łapie kolejny przebieg; outbox z ponawianiem. |
| Sekwencje: dziekanat, harmonogram, wymagania + import, logowanie | Krótko: limit +1 nie ponad salę; blokady doradcze przy kolizjach sal; cykl wymagań pod blokadą; import z raportem błędów; bcrypt w wątku. |
| ER + co nowe | `program`, `round_program`, jedna `app_user`, `created_by`. Reguły usunięte z bazy. (§6) |
| Klasy: domena + tabela | `check_student` / `decide_seat` – dwa kroki odpowiadające dwóm blokadom. Wszystko na niezmiennych dataclassach. (§7.1) |
| Klasy: serwisy + EnrollmentService | Moduł = serwis, funkcja = operacja = jedna transakcja. Parametry, wyniki. (§7.2) |
| Klasy: infrastruktura | `TTLCache`, `RateLimiter`, `Gate`, `run_transaction` z ponowieniami. (§7.3) |
| 20 000 studentów | Najpierw ograniczyć ruch (tury per kierunek), potem obsłużyć (krótkie blokady, kontrola wejścia, cache, bez ORM, skalowanie). |
| Test obciążeniowy | Pierwsza wersja nie przeszła – kaskada 429 z błędnego liczenia limitu. Po poprawkach 0 ponowień, p95 1,9 s. Przeciążenie 3× – wolniej, ale spójnie. |
| Ekrany | Dowód, że projekt działa: powody odmowy przy grupach, rozłożenie tur. |
| Weryfikacja i przekazanie | 35 testów, wyścigi; jak rozwijać (domena + test, migracja Alembic); znane ograniczenia. |

## Pytania prowadzącego – przygotowane odpowiedzi

**P: Dlaczego reguły w kodzie, a nie w bazie (w etapie 2 były funkcje SQL)?**
O: Reguły to decyzje biznesowe, które się zmieniają (np. nowy typ zajęć, wyjątki dziekanatu).
W Pythonie są czytelne, testowane jednostkowo w milisekundach bez bazy i mają jedno miejsce
– ten sam `check_student` liczy podgląd dla UI i decyzję przy zapisie. W bazie zostało to,
czego aplikacja sama nie zagwarantuje przy współbieżności: ograniczenia i blokady.

**P: Skoro reguły są w aplikacji, co jeśli kod ma błąd?**
O: Baza odrzuci wynik: `CHECK (enrolled_count <= capacity)`, `UNIQUE … WHERE status='ENROLLED'`
(jeden aktywny zapis), `UNIQUE … WHERE status='WAITING'`, `CHECK` na statusach. Mieliśmy taki
przypadek – opisany na slajdzie „Architektura: zasady”. Audyt niezmienników co minutę wykryje
resztę (np. licznik niezgodny z liczbą zapisów).

**P: Czy podgląd statusu grup (UC19) może kłamać?**
O: Może być nieaktualny o ułamek sekundy – liczony bez blokad. Ostateczna decyzja zapada
w transakcji UC2 pod blokadami, więc najwyżej przycisk „Zapisz” skończy się odmową z powodem.

**P: Dlaczego klucz obcy `enrollment.student_id` wskazuje na `app_user`, a nie na studenta?**
O: Po połączeniu tabel jest jedna tabela kont. Rolę sprawdza blokada studenta
(`WHERE role='STUDENT'`) – brak wiersza = odmowa. W bazie dałoby się to wymusić złożonym
kluczem `(student_id, 'STUDENT') → app_user(id, role)`, kosztem dodatkowej kolumny w czterech
tabelach; uznaliśmy, że nie warto.

**P: Jak działa tura per kierunek? Co jeśli kierunki się nakładają?**
O: `round_program` łączy turę z kierunkami; tura bez kierunków obejmuje wszystkich. Student może
się zapisywać, gdy jakakolwiek otwarta tura semestru obejmuje jego kierunek (`student_can_enroll`).
Nakładanie się jest dozwolone. Zamknięcie tury wygasza listy tylko tych kierunków, których żadna
otwarta tura już nie obejmuje (`expire_uncovered`).

**P: Czy wcześniejsza tura kierunku A nie zabierze miejsc studentom B we wspólnych przedmiotach?**
O: Tak – to znane ograniczenie: kursy nie są przypisane do kierunków, tura reguluje *kto i kiedy*,
a nie *na co*. Rozszerzenie: tabela `program_course` i reguła w `check_student`
(np. w turze 1 tylko przedmioty swojego kierunku) – jedna funkcja domeny i jedna tabela.

**P: Skąd wiadomo, że system wytrzyma?**
O: Z pomiaru, nie z założeń: k6, 1000 studentów jednego kierunku naraz, każdy ok. 20 operacji.
p95 zapisu 1,9 s, zero ponowień, niezmienniki spełnione. Przy 3 kierunkach naraz (3000 osób) system
zwalnia i odsyła część żądań do ponowienia (0,5% zapisów zrezygnowało po 6 próbach), ale nie
przepełnia grup. Wąskie gardło to CPU API, więc kolejne instancje API zwiększają przepustowość.

**P: Co znaleźliście dzięki testom obciążeniowym?**
O: (1) Limit operacji liczył też ponowienia po 503, więc studenci wpadali w kaskadę 429 –
teraz odrzucenie przez bramkę zwraca limit. (2) Podgląd statusu robił ok. 50 zapytań na kurs –
teraz 3 hurtowe. (3) Narzut ORM w gorącej ścieżce – zapytania przez asyncpg. Przepustowość
wzrosła z ok. 75 do ok. 330 decyzji/s na tej samej maszynie.

**P: Po co bramka (Gate), skoro baza ma pulę połączeń?**
O: Bez niej nadmiar żądań czeka w kolejce do puli, trzymając połączenia HTTP i pamięć, aż do
timeoutu. Bramka szybko odpowiada 503 z `Retry-After`, a SPA ponawia z losowym rozrzutem – ruch
rozkłada się w czasie zamiast piętrzyć.

**P: Dlaczego JWT ważny 12 h? To bezpieczne?**
O: Przy otwarciu tury nikt nie powinien się logować – bcrypt kosztuje ok. 50 ms CPU. Token jest
podpisany kluczem z konfiguracji, ma rolę i czas ważności. Słabość: nie da się go unieważnić przed
czasem (np. przy zmianie roli). Docelowo SSO uczelni.

**P: Co jeśli worker padnie w trakcie zamykania tury?**
O: Zamknięcie i wygaszenie list to jedna transakcja – albo całe, albo wcale. Worker po restarcie
w kolejnym przebiegu zobaczy turę z `closes_at` w przeszłości i ją zamknie. Można uruchomić kilka
workerów: tury i outbox są brane przez `SKIP LOCKED`.

**P: Czy e-mail może przyjść dwa razy?**
O: Tak (dostarczenie „co najmniej raz”): jeśli SMTP przyjmie wiadomość, a worker padnie przed
zapisaniem `sent_at`. Powiadomienie nigdy nie zginie i nie zostanie wysłane dla wycofanej zmiany.

**P: Dlaczego moduły, a nie klasy w Pythonie? Czy to jest „projekt klas”?**
O: Serwisy nie mają stanu – stan jest w bazie, a dane między warstwami to niezmienne dataclassy.
Moduł z funkcjami jest odpowiednikiem klasy-serwisu ze statycznymi metodami; na diagramach
oznaczony `<<service>>`. Klasy ze stanem tam, gdzie stan jest: `TTLCache`, `RateLimiter`, `Gate`.

**P: Jak grupa przejmująca ma dodać nową funkcję?**
O: Regułę – w `app/domain` z testem jednostkowym; dane do niej w `loaders`; transakcję w serwisie;
endpoint w `app/api`; schemat – migracja Alembic i `etap3/diagramy/er.py`. Każda zmiana w ścieżce
zapisu: test wyścigu i test obciążeniowy (`../IMPLEMENTACJA.md`).

## Znane słabości (powiedzieć samemu, zanim padnie pytanie)

1. Kursy nieprzypisane do kierunków (patrz wyżej).
2. Brak zamiany grupy (L05 → L03 bez utraty L05).
3. Limit żądań i cache per proces – przy N instancjach limit przybliżony (rozwiązanie: Redis).
4. Zmiana terminu przez dziekanat w trakcie tury: inne procesy widzą ją po ≤ 10 s; plany już
   zapisanych studentów nie są ponownie sprawdzane.
5. Jedna rola na konto.
6. Testy obciążeniowe na jednej maszynie razem z generatorem ruchu – wyniki zaniżone względem
   osobnych serwerów.
