# Etap 2 – pełny opis do prezentacji i przygotowanie do pytań

System zapisów na zajęcia (temat 2), Inżynieria Oprogramowania, zima 2026/2027, prezentacja 21.X.
Zespół: Kamil Kręcigłowa, Bartosz Królik, Krzysztof Krówka.

Jak korzystać z tego pliku:

- **Część A:** co dokładnie mamy i w jakim stanie. Każda odpowiedź na pytanie musi się z tym
  zgadzać. Nigdy nie mówimy, że coś „działa”, jeśli tylko to zaprojektowaliśmy.
- **Część B:** plan wystąpienia pod krótkie slajdy (`prezentacja/prezentacja_krotka.pdf`,
  maks. 10 minut).
- **Część C:** pełny tekst do powiedzenia, slajd po slajdzie. Nie trzeba go czytać, ale każdy
  powinien umieć powiedzieć swoją część własnymi słowami.
- **Część D:** pokaz prototypu na żywo (opcjonalny).
- **Część E:** bank pytań prowadzącego („po co?”, „dlaczego?”, „jak dokładnie?”) z odpowiedziami
  i dopytaniami.
- **Część F:** słabe punkty, które znamy. Lepiej powiedzieć je samemu, zanim znajdzie je prowadzący.
- **Część G:** ściąga liczb i nazw.

---

## A. Stan projektu – co jest gotowe, a co tylko zaprojektowane

Etap 2 wymaga architektury, prototypów obszarów ryzyka (albo mock-upów), głównych przypadków
użycia i projektu struktury danych (ER). Mamy wszystkie cztery elementy, plus mock-up.

| Element | Plik | Stan |
|---|---|---|
| Diagram architektury | `diagramy/architektura.puml/.png` | **zaprojektowane** |
| Stos technologiczny (React, FastAPI, PostgreSQL, worker, JWT, Docker Compose) | README, sekcja 1 | **tylko wybór i uzasadnienie**, brak kodu |
| Przypadki użycia UC0–UC18 | `diagramy/przypadki_uzycia_*.puml/.png`, README sekcja 2 | **zaprojektowane**, główne scenariusze rozpisane |
| Diagram ER | `diagramy/er.py` → `er.tex/.pdf/.png` | **zaprojektowane** (generowane skryptem z opisu tabel) |
| Schemat bazy | `schemat.sql` | **sprawdzony na PostgreSQL 16** (wczytuje się, ograniczenia działają – patrz niżej) |
| Prototyp 6 scenariuszy ryzyka | `prototyp/prototyp_zapisow.py` | **działa** (Python + SQLite, wątki), wynik powtarzalny |
| Test zakleszczenia i `NOWAIT` | ręcznie, dwie sesje `psql` | **sprawdzony na PostgreSQL 16** |
| Mock-up ekranu studenta | `mockup/mockup.html/.png` | **statyczny HTML**, bez logiki |
| Slajdy | `prezentacja/*.tex/.pdf` | gotowe (pełne i krótkie) |
| Odpowiedzi na wcześniejsze pytania | `notes.md` | gotowe |

Co **sprawdziliśmy na PostgreSQL 16** (ostatnio ponownie 20.10.2026, czysty kontener `postgres:16`):

- `schemat.sql` wczytuje się bez błędów.
- Zwykłe `FOR UPDATE` przy awansie (grupa → student B) razem z zapisem B (student B → grupa)
  kończy się `ERROR: deadlock detected`. Z `FOR UPDATE NOWAIT` awans od razu dostaje
  `could not obtain lock on row` (SQLSTATE 55P03), więc zakleszczenia nie ma.
- Trigger odrzuca cykl wymagań (A wymaga B, B wymaga A).
- Indeks częściowy nie pozwala otworzyć dwóch tur naraz w jednym semestrze.
- `CHECK (enrolled_count <= capacity)` nie pozwala zmniejszyć limitu poniżej liczby zapisanych
  (limit 3 → 1 przy 2 zapisanych: błąd).
- Widok `section_invariant_violations` wykrywa zapis bez zwiększenia licznika.
- `passed` wylicza się z oceny (2.0 → `false`).
- Warunkowy `UPDATE ... WHERE enrolled_count < capacity` w dwóch równoległych sesjach
  o ostatnie miejsce: druga sesja czeka, po zatwierdzeniu pierwszej ponownie sprawdza warunek
  i nic nie zmienia (licznik kończy na 2/2, a nie 3/2).

Czego **nie ma** (i nie twierdzimy, że jest):

- kodu backendu i frontendu,
- limitu żądań, JWT, SSO, workera (to decyzje projektowe),
- testu wydajności,
- wykrywania kolizji sal i prowadzących w SQL lub prototypie (tylko opisane w UC12),
- obsługi ponawiania transakcji w kodzie (opisana w `schemat.sql`, test zrobiony ręcznie).

---

## B. Plan wystąpienia (krótkie slajdy, ok. 10 minut)

Podział osób jest propozycją. Ustalcie go przed zajęciami i niech każdy zna też części pozostałych,
bo pytania mogą trafić do każdego.

| # | Slajd | Czas | Kto (propozycja) |
|---|---|---|---|
| 1 | Tytuł | 0:15 | Kamil |
| 2 | Pokrycie wymagań | 0:45 | Kamil |
| 3 | Diagram architektury | 1:00 | Kamil |
| 4 | Architektura i stos technologiczny | 1:00 | Kamil |
| 5 | Przypadki użycia 1/2 (student) | 1:00 | Bartosz |
| 6 | Przypadki użycia 2/2 (dziekanat, prowadzący, zegar) | 1:00 | Bartosz |
| 7 | Kluczowe scenariusze: UC2 i UC9 | 1:00 | Bartosz |
| 8 | Diagram ER | 1:15 | Krzysztof |
| 9 | Scenariusz 1: 30 studentów, 10 miejsc | 1:00 | Krzysztof |
| 10 | Blokady w PostgreSQL: zakleszczenie przy awansie | 0:45 | Krzysztof |
| 11 | Mock-up | 0:30 | Bartosz |
| 12 | Podsumowanie | 0:20 | Kamil |
| | **Razem** | **ok. 9:50** | |

Jeśli prowadzący da więcej czasu, użyjcie pełnej wersji (`prezentacja.pdf`). Ma dodatkowo:
- rozpisane UC2 i UC9,
- slajd z decyzjami w modelu danych,
- slajd z regułą kolizji i tabelą przypadków,
- slajd ze scenariuszami 4–6.

---

## C. Pełny opis – co mówimy przy każdym slajdzie

### Slajd 1 – Tytuł

„Dzień dobry. Jesteśmy zespołem tematu drugiego, *System zapisu na zajęcia*. Pokażemy etap
drugi: architekturę, przypadki użycia, model danych i prototypy miejsc, w których naszym zdaniem
najłatwiej o błąd.”

### Slajd 2 – Pokrycie wymagań

„Zaczęliśmy od rozbicia tematu na sześć wymagań:
- ograniczona liczba miejsc,
- katalog kursów, grup, prowadzących i harmonogramów,
- różne rozmiary grup,
- wymagania wstępne,
- wykrywanie kolizji w planie,
- listy oczekujących z automatycznym zapisem.

Tabela pokazuje dla każdego wymagania, który przypadek użycia je realizuje, które tabele
w bazie je przechowują i który scenariusz prototypu je sprawdza. Każde wymaganie ma pokrycie
we wszystkich trzech miejscach. Katalog prototyp sprawdza tylko częściowo, przez tury zapisów,
bo samo dodawanie kursów i sal to zwykłe formularze bez ryzyka.”

### Slajd 3 – Diagram architektury

„To klasyczna aplikacja webowa w trzech warstwach plus proces w tle.
- **Prezentacja:** jedna aplikacja SPA w przeglądarce dla trzech ról: studenta, prowadzącego
  i dziekanatu.
- **Backend:** REST API w FastAPI podzielone na moduły według odpowiedzialności.
  - `CatalogService` zarządza katalogiem: kursy, grupy, sale, terminy, tury zapisów.
  - `EnrollmentService` obsługuje zapisy i wypisy. To **jedyny** moduł, który zmienia liczbę
    zajętych miejsc, więc logika miejsc jest w jednym miejscu.
  - Dwa moduły reguł: `PrerequisiteChecker` sprawdza zaliczone przedmioty, a
    `ScheduleConflictDetector` kolizje w planie.
  - `WaitlistService` prowadzi kolejki oczekujących i automatyczny awans.
  - `NotificationService` zapisuje powiadomienia do tabeli-outboxa.
  - Do tego `UserService` i `StudentRecordsService` do importu ocen.
- **Worker w tle:** otwiera i zamyka tury o zadanych godzinach, wygasza listy oczekujących,
  okresowo sprawdza niezmienniki i wysyła e-maile.
- **PostgreSQL:** jedno źródło prawdy.”

### Slajd 4 – Architektura i stos technologiczny

„Najtrudniejszy moment dla systemu to otwarcie tury: setki studentów w tej samej sekundzie
próbują zająć te same miejsca. Dlatego całą spójność opieramy na transakcjach bazy:
- zapisy do jednej grupy kolejno ustawia blokada wiersza tej grupy,
- zapisy jednego studenta blokada wiersza tego studenta,
- zapisy różnych studentów do różnych grup idą równolegle.

Stos technologiczny:
- **PostgreSQL:** ma transakcje ACID, blokady pojedynczych wierszy, indeksy częściowe
  i typy `TIME` oraz `JSONB`.
- **FastAPI:** szybko się w nim prototypuje i sam generuje dokumentację OpenAPI.
- **React z TypeScriptem** na froncie.
- **Bez osobnego brokera kolejek:** powiadomienia i harmonogram tur są w bazie, więc wystarczy
  prosty worker.

To decyzje projektowe. Kodu backendu jeszcze nie ma, mamy prototyp mechanizmów.”

### Slajd 5 – Przypadki użycia 1/2 (student)

„Aktorem jest student. Notację wzorowaliśmy na przykładzie bankomatu z uml-diagrams.org:
- **Asocjacje:** aktor jest połączony z przypadkami zwykłą linią bez strzałki.
- **Abstrakcyjny przypadek:** *Operacja studenta*, zapisana kursywą, uogólnia wszystkie operacje
  studenta i przez `include` wymaga UC0, czyli uwierzytelnienia. Dzięki temu nie rysujemy
  `include` do logowania z każdego przypadku osobno.
- **Zapis (UC2) przez `include`:** zawsze sprawdza wymagania wstępne (UC3) i kolizje (UC4).
- **Lista oczekujących (UC5) przez `extend`:** rozszerza zapis w nazwanym punkcie rozszerzenia
  „brak wolnych miejsc”, bo dzieje się tylko wtedy, gdy grupa jest pełna.
- **Wypis (UC6) przez `include` UC9:** wypis zawsze uruchamia awans pierwszego z listy.
  Student może się wypisać tylko w otwartej turze, więc wypis zawsze zwalnia miejsce, na które
  ktoś może awansować.”

### Slajd 6 – Przypadki użycia 2/2 (dziekanat, prowadzący, zegar)

„Na drugim diagramie są pracownicy i zegar systemowy.
- **Prowadzący (UC10):** przegląda listy swoich grup.
- **Dziekanat:**
  - zarządza kursami i wymaganiami (UC11) oraz grupami, salami i harmonogramem (UC12).
    Przy dodawaniu terminu sprawdzamy kolizje sal i prowadzących, stąd `include` UC4,
  - zmienia limity (UC13), zapisuje i wypisuje studentów decyzją dziekanatu (UC14),
    importuje oceny (UC15) i ręcznie otwiera albo zamyka turę (UC16).
- **Zegar systemowy:** osobny aktor z osobnym przypadkiem UC17. Otwiera i zamyka turę
  o godzinie z harmonogramu, ale w przeciwieństwie do dziekanatu się nie uwierzytelnia.
  Dlatego UC17 nie dziedziczy po *Operacji pracownika*.
- **Zamknięcie tury:** zarówno ręczne, jak i automatyczne, przez `include` wygasza listy
  oczekujących (UC18).
- **Awans z listy (UC9):** rozszerza UC13 i UC14 przez `extend`, bo tam jest warunkowy.
  Zmiana limitu nie zawsze zwalnia miejsce, a wypis przez dziekanat po turze nikogo nie zapisuje.”

### Slajd 7 – Kluczowe scenariusze: UC2 i UC9

„Zapis do grupy wygląda tak:
1. System blokuje wiersz studenta, a potem wiersz grupy, zawsze w tej kolejności.
2. Sprawdza po kolei:
   - czy tura jest otwarta,
   - czy student nie jest już zapisany do tej grupy ani na nią nie czeka,
   - czy nie ma już grupy tego samego przedmiotu i typu (wykład i laboratorium z IO wolno,
     dwa laboratoria nie),
   - wymagania wstępne,
   - kolizje.
3. Jeśli jest miejsce, zapisuje studenta i zwiększa licznik. Jeśli nie ma, dopisuje go na koniec
   listy oczekujących, o ile lista nie przekroczyła limitu.
4. Każda odmowa podaje konkretną przyczynę, na przykład z którą grupą jest kolizja.

Awans z listy dzieje się w **tej samej transakcji**, która zwolniła miejsce. Inaczej w krótkiej
chwili między wypisem a awansem ktoś spoza listy mógłby zająć miejsce i przeskoczyć kolejkę.
- Oczekujących bierzemy po kolei i każdego **sprawdzamy ponownie**, bo od dopisania mógł się
  zapisać na coś w tym samym terminie.
- Kto nie spełnia warunków, dostaje status SKIPPED z powodem i powiadomienie.
- Bez wolnego miejsca nikogo nie pomijamy: oczekujący może jeszcze usunąć kolizję, zanim
  miejsce się zwolni.

Pilnujemy niezmiennika: nikt nie czeka na liście, gdy w grupie są wolne miejsca.”

### Slajd 8 – Diagram ER

„Diagram jest generowany skryptem `er.py` do TikZ, a linie łączą konkretną kolumnę klucza obcego
z kluczem głównym. Najważniejsze decyzje:
- **Kurs to nie grupa.** `course` to przedmiot w katalogu. `section` to konkretna grupa
  w semestrze, z własnym typem i limitem. Dlatego jeden kurs może mieć wykład na 150 osób
  i laboratoria po 15.
- **Harmonogram w osobnej tabeli `meeting`.** Grupa może mieć kilka terminów w tygodniu, a termin
  ma dzień, godziny, parzystość tygodni i salę.
- **Licznik `enrolled_count` w grupie.** Dzięki niemu sprawdzenie limitu i zajęcie miejsca to
  jeden warunkowy `UPDATE`.
- **Historia zamiast kasowania.** Wypis zmienia status na DROPPED, a wpis na liście ma statusy
  PROMOTED, SKIPPED, CANCELLED i EXPIRED. Indeksy częściowe pilnują, żeby aktywny był tylko jeden
  zapis i jeden wpis na liście.
- **Kolejność na liście** to `id` z sekwencji, bez kolumny „pozycja”, więc rezygnacja nie wymaga
  przenumerowania.
- **Tury zapisów w `enrollment_round`.** W semestrze otwarta może być najwyżej jedna.
- **Ochrona danych:** `passed` jest wyliczane z oceny, a trigger blokuje cykle wymagań.
- **Powiadomienia przez outbox.** Zapisujemy je w tej samej transakcji, a wysyła je worker.

Schemat jest sprawdzony na PostgreSQL 16.”

### Slajd 9 – Scenariusz 1: 30 studentów, 10 miejsc

„Za największe ryzyko uznaliśmy wyścig o ostatnie miejsca, więc od niego zaczęliśmy prototyp.
Prototyp to skrypt w Pythonie na SQLite, tylko z biblioteką standardową. Trzydzieści wątków
startuje jednocześnie dzięki barierze.
- **Wersja naiwna** najpierw odczytuje licznik, a potem osobno zapisuje. Wynik: 30 zapisanych
  na 10 miejsc, a licznik pokazuje 1, bo każdy wątek nadpisał go wartością policzoną na
  początku. Ważne: `CHECK` na liczniku tego nie wykrył, bo licznik jest zaniżony, a nie
  przekroczony. Wykrywa to dopiero widok audytu niezmienników.
- **Wersja bezpieczna** robi sprawdzenie i zajęcie miejsca jednym atomowym `UPDATE` z warunkiem
  `enrolled_count < capacity`. Gdy nie zmieni żadnego wiersza, grupa jest pełna i student trafia
  na listę. Wynik jest zawsze ten sam: 10 zapisanych, 20 na liście.

Prototyp ma jeszcze pięć scenariuszy:
- wymagania wstępne,
- pięć przypadków kolizji, w tym styk końcem i tygodnie parzyste,
- listę oczekujących z pominięciem osoby z kolizją i dwoma równoczesnymi wypisami,
- regułę jednej grupy danego typu,
- decyzje dziekanatu i zamknięcie tury.

Po każdym scenariuszu sprawdzamy niezmienniki.”

### Slajd 10 – Blokady w PostgreSQL

„Przy projektowaniu blokad znaleźliśmy problem, którego prototyp na SQLite nie pokaże, bo SQLite
blokuje całą bazę.
- Zwykły zapis blokuje studenta, potem grupę.
- Awans z listy po wypisie trzyma już blokadę grupy, a potrzebuje blokady awansowanego
  studenta B, żeby jego plan nie zmienił się w trakcie sprawdzania. To odwrotna kolejność.
- Jeśli B w tej samej chwili zapisuje się do tej grupy, mamy zakleszczenie. Sprawdziliśmy to
  na dwóch sesjach PostgreSQL 16 i dostaliśmy `deadlock detected`.

Rozwiązanie: awans blokuje B z opcją `NOWAIT`. Jeśli B jest zajęty, transakcja od razu dostaje
błąd, jest wycofywana i ponawiana po chwili. Nie pomijamy B, bo straciłby kolejkę. Tak samo
ponawiamy transakcję przy błędzie zakleszczenia (40P01) i serializacji (40001).”

### Slajd 11 – Mock-up

„Mock-up to statyczny ekran zapisów studenta w HTML. Widać na nim:
- **katalog z zajętością miejsc,**
- **kurs zablokowany przez wymagania:** ZIO jest niedostępny, bo IO niezaliczone,
- **przycisk „Zapisz” zablokowany kolizją:** z informacją, z którą grupą,
- **listę oczekujących:** pozycję na liście z przyciskiem „Zrezygnuj” i „Dołącz do listy”
  przy pełnej grupie,
- **ostrzeżenie przy zapisie:** zapis na L05 usunie studentkę z listy L03,
- **plan tygodnia:** zajęcia co dwa tygodnie są zakreskowane,
- **powiadomienia:** o automatycznym zapisie i o pominięciu.

Chcieliśmy, żeby student zawsze wiedział, **dlaczego** czegoś nie może zrobić.”

### Slajd 12 – Podsumowanie

„Gotowe są: architektura, przypadki użycia UC0–UC18, model danych ze schematem sprawdzonym na
PostgreSQL, prototyp sześciu scenariuszy ryzyka i mock-up. W etapie trzecim planujemy:
- diagramy sekwencji,
- diagram klas z metodami,
- uprawnienia ról i obsługę błędów,
- test blokad i wydajności na PostgreSQL,
- zamianę grupy bez utraty miejsca.

Dziękujemy, chętnie odpowiemy na pytania.”

---

## D. Pokaz prototypu na żywo (jeśli prowadzący poprosi)

```bash
cd prototyp
python3 prototyp_zapisow.py
```

Działa bez instalowania czegokolwiek (Python 3, biblioteka standardowa), trwa około sekundy
i kończy się linią `Wszystkie niezmienniki spełnione.`

Co pokazać i powiedzieć:

1. **Scenariusz 1:** „Wersja naiwna zapisała więcej osób, niż jest miejsc, a licznik jest
   zaniżony. Bezpieczna zawsze daje 10 i 20.”
2. **Scenariusz 4:** „Student 3 czekał pierwszy, ale w międzyczasie zapisał się na kolidujące
   BD L05. Przy wypisie system go pominął (SKIPPED z powodem) i zapisał następnego. Gdy miejsca
   nie było, nikt nie został pominięty. Dwa równoczesne wypisy zapisały dokładnie dwie pierwsze
   osoby z listy.”
3. **Koniec:** wszystkie asercje i niezmienniki przeszły.

Uwaga: liczby w wersji naiwnej mogą się różnić między uruchomieniami (np. 27 zamiast 30, licznik
2 zamiast 1). Jeśli prowadzący zapyta „dlaczego tym razem inaczej?”, odpowiadamy: „To wyścig, wynik
zależy od kolejności, w jakiej system operacyjny przełącza wątki. Właśnie dlatego ten błąd jest
groźny: w testach może się nie pokazać. Wersja bezpieczna daje zawsze ten sam wynik, a skrypt
sprawdza to asercją.”

---

## E. Bank pytań

Format: **P:** pytanie, **O:** odpowiedź, **Dopytanie:** co odpowiedzieć, jeśli prowadzący
drąży dalej.

### E1. Ogólne i zakres

**P: Co właściwie jest gotowe? Macie działający system?**
O: Nie, i etap tego nie wymaga. Mamy architekturę, przypadki użycia, model danych w postaci
schematu SQL sprawdzonego na PostgreSQL 16, działający prototyp najbardziej ryzykownych
mechanizmów oraz mock-up. Backend i frontend to następne etapy.
Dopytanie, „to po co prototyp?”: żeby przed pisaniem systemu sprawdzić, czy pomysł na
spójność miejsc i listy oczekujących w ogóle działa. Gdyby nie działał, musielibyśmy zmienić
architekturę, a teraz to tanie.

**P: Dlaczego uznaliście akurat te obszary za problematyczne?**
O: Bo tam błąd jest najdroższy i najtrudniejszy do zauważenia:
- **Wyścig o miejsca:** błąd wychodzi tylko przy dużym obciążeniu, czyli dokładnie w chwili
  otwarcia zapisów.
- **Lista oczekujących:** łączy kilka trudnych rzeczy naraz: kolejność, równoczesne wypisy
  i ponowne sprawdzanie reguł.
- **Kolizje:** mają przypadki brzegowe (styk końcem, parzystość tygodni), w których łatwo
  o pomyłkę o jeden.

CRUD katalogu (dodaj kurs, dodaj salę) nie niesie ryzyka, więc go nie prototypowaliśmy.

**P: Czym różnicie się od USOS?**
O: Nie konkurujemy z USOS-em. Projektujemy system z tematu. Rozwiązujemy jednak problemy, które
każdy zna z zapisów: przeciążenie przy otwarciu tury, niejasne odmowy, ręczne listy rezerwowe.
U nas lista oczekujących jest automatyczna, a każda odmowa podaje przyczynę.

**P: Po tym etapie projekt przejmie inna grupa. Czy zrozumie wasz materiał?**
O: Taki był cel:
- **README:** tabela „wymaganie → przypadek użycia → tabele → scenariusz prototypu”.
- **Schemat SQL:** ma komentarze z uzasadnieniami i szkic transakcji zapisu i awansu.
- **`notes.md`:** opisuje każdą tabelę i relację.
- **Regeneracja:** diagramy można odtworzyć ze źródeł (PlantUML, skrypt `er.py`).
- **Prototyp:** uruchamia się jednym poleceniem i jest jednocześnie testem.

### E2. Architektura

**P: Dlaczego monolit z modułami, a nie mikroserwisy?**
O: Najważniejsza operacja (zapis, sprawdzenie reguł, awans z listy, powiadomienie) musi być
**jedną transakcją**. W mikroserwisach każdy serwis ma swoją bazę i to samo wymagałoby
rozproszonych transakcji albo sag z kompensacją. Byłoby to dużo bardziej skomplikowane i dawało
więcej możliwości błędu. Moduły w jednym procesie dają podział odpowiedzialności bez tego kosztu.
Skalowanie poziome i tak jest możliwe: uruchamiamy kilka instancji API, bo stan jest w bazie.
Dopytanie, „a jeśli baza będzie wąskim gardłem?”: wąskim gardłem jest jedna popularna
grupa, a nie cała baza. Zapisy do różnych grup idą równolegle. Repliki do odczytu katalogu są
możliwe, bo katalog czyta się dużo częściej, niż się go zmienia.

**P: Po co osobny worker? Nie wystarczy API?**
O: Są zadania, które nie są odpowiedzią na żądanie użytkownika:
- otwarcie i zamknięcie tury o zadanej godzinie,
- wysyłka e-maili,
- okresowy audyt niezmienników.

Wysyłka e-maili w transakcji zapisu byłaby błędem: wolny serwer SMTP wydłużałby trzymanie
blokad, a e-maila nie da się wycofać, gdy transakcja się nie powiedzie.

**P: Dlaczego nie RabbitMQ, Kafka albo Redis?**
O: Na naszą skalę wystarcza baza. Outbox w tabeli `notification` ma właściwość, której broker
nie da bez dodatkowej pracy: powiadomienie zapisuje się atomowo razem ze zmianą. Jeśli
transakcja się wycofa, powiadomienia nie ma. Z brokerem trzeba by rozwiązać problem „zapisano
w bazie, ale nie wysłano do kolejki” (albo odwrotnie). Jeden komponent mniej do utrzymania.

**P: Co znaczy „EnrollmentService to jedyny moduł zmieniający liczbę miejsc”? Przecież
WaitlistService też zapisuje.**
O: WaitlistService wybiera kandydata z kolejki, ale sam zapis (zajęcie miejsca, licznik, wiersz
`enrollment`) wykonuje przez EnrollmentService. Na diagramie to strzałka „zapis awansowanego”.
Dzięki temu warunkowy `UPDATE` licznika jest w jednym miejscu kodu i nie da się go ominąć.

**P: Dlaczego FastAPI i Python? To nie jest wolne?**
O: Wąskim gardłem przy zapisach są blokady i transakcje w bazie, a nie szybkość języka. Python
z FastAPI pozwala szybko budować, sam generuje dokumentację OpenAPI i waliduje dane przez
Pydantic. Prototyp też jest w Pythonie, więc zespół zna narzędzie.

**P: Jak radzicie sobie z obciążeniem przy otwarciu tury? Ile żądań wytrzyma system?**
O: Uczciwie: nie mierzyliśmy tego, to plan na następny etap. Szacunek: zapis to kilka zapytań
i jedna krótka transakcja, rzędu milisekund.
- **Kolejka do jednej grupy:** zapisy do niej ustawiają się w kolejce na blokadzie jej wiersza.
  Przy 300 chętnych na laboratorium i około 10 ms na transakcję ostatni czeka około 3 sekund.
- **Różne grupy:** zapisy idą równolegle.
- **Ochrona przed botami:** limit żądań na użytkownika.

Dopytanie, „co jeśli 3 sekundy to za długo?”: można przejść na model kolejkowy (żądania
przyjmowane od razu, wynik przez powiadomienie), ale to komplikuje interfejs. Najpierw zmierzymy.

**P: Co z bezpieczeństwem?**
O: Na razie to decyzje projektowe:
- **Uwierzytelnianie:** JWT, docelowo SSO uczelni.
- **Hasła:** trzymamy tylko jako hash, docelowo bcrypt albo argon2.
- **Uprawnienia:** role w `app_user.role`, sprawdzane w API (student widzi tylko swoje zapisy,
  prowadzący tylko swoje grupy).
- **Ruch:** HTTPS i limit żądań.

Szczegóły uprawnień są zaplanowane na etap 3.

### E3. Przypadki użycia i notacja UML

**P: Jaka jest różnica między `include` a `extend`? Dlaczego tu jedno, a tam drugie?**
O: `include` oznacza, że zachowanie wykonuje się **zawsze**, a strzałka idzie od przypadku
bazowego do włączanego. Przykład: zapis zawsze sprawdza wymagania i kolizje.
`extend` oznacza zachowanie **warunkowe**, które wchodzi w nazwanym punkcie rozszerzenia,
a strzałka idzie od rozszerzenia do przypadku bazowego. Przykład: lista oczekujących (UC5)
rozszerza zapis tylko przy braku miejsc. UC2 jest kompletny sam w sobie, bo zapis się udaje.
Dopytanie, „to dlaczego UC9 jest raz `include` (z UC6), a raz `extend` (do UC13, UC14)?”:
- **UC6:** student wypisuje się tylko w otwartej turze, więc zawsze zwalnia miejsce i awans
  zawsze się uruchamia.
- **UC13:** zmiana limitu może go zmniejszyć, wtedy wolnego miejsca nie ma.
- **UC14:** wypis przez dziekanat może się zdarzyć po turze, gdy listy już wygasły.

W UC13 i UC14 awans jest warunkowy, więc to `extend` z nazwanymi punktami „wolne miejsce po
zmianie” i „wypis w otwartej turze”.

**P: UC9 nie ma aktora. Czy to poprawne?**
O: Tak. Przypadek użycia, który jest tylko włączany (`include`) lub rozszerza inny, nie musi mieć
własnej asocjacji z aktorem. Wykonuje się w ramach przypadku bazowego, który aktora ma. UC9 to
reakcja systemu na zwolnienie miejsca, a nie coś, co ktoś świadomie uruchamia.

**P: Czy UC3 i UC4 jako osobne przypadki to nie jest dekompozycja funkcjonalna? Przypadek
użycia powinien dawać aktorowi wartość.**
O: To zasadny zarzut. Wyodrębniliśmy je świadomie, bo są **współdzielone**:
- UC4 (kolizje) używa zarówno zapis (UC2), jak i układanie harmonogramu (UC12) oraz zapis przez
  dziekanat (UC14),
- UC3 i UC4 używa też awans z listy (UC9).

`include` służy właśnie do wyciągnięcia wspólnego zachowania wielu przypadków, żeby nie opisywać
go kilka razy. Dlatego nie mają własnego aktora.

**P: Po co abstrakcyjne przypadki „Operacja studenta” i „Operacja pracownika”?**
O: Żeby nie rysować `include` do UC0 z każdego z kilkunastu przypadków. Wszystkie konkretne
operacje uogólniają przypadek abstrakcyjny (strzałka z pustym grotem), a on raz włącza
uwierzytelnienie. To ten sam zabieg, co w przykładzie bankomatu na uml-diagrams.org.

**P: Dlaczego zegar systemowy jest aktorem? To przecież część systemu.**
O: W UML aktorem jest wszystko spoza systemu, co inicjuje przypadek użycia: człowiek, inny
system albo czas. Upływ czasu (godzina otwarcia tury) jest zdarzeniem zewnętrznym, którego
system nie kontroluje. Dlatego zegar jest aktorem, a jego przypadek UC17 jest osobny od UC16:
dziekanat się uwierzytelnia, zegar nie.

**P: Dlaczego nie ma przypadku „zaloguj się” powiązanego bezpośrednio z aktorem?**
O: Logowanie samo w sobie nie daje wartości, jest warunkiem innych operacji. Dlatego jest
włączane przez abstrakcyjne przypadki. Można by je też pokazać jako warunek wstępny w opisie
scenariusza i tak też robimy („student jest zalogowany”).

**P: Czemu dwa diagramy, a nie jeden?**
O: Pierwsza wersja na jednym diagramie była nieczytelna: kilkanaście linii uogólnienia się
krzyżowało. Podzieliliśmy według aktorów. Wspólne przypadki (UC0, UC4, UC9) występują na obu.

**P: Gdzie jest scenariusz alternatywny dla UC2? Co, jeśli coś pójdzie nie tak w połowie?**
O: W README, przy UC2. Scenariusze alternatywne:
- brak zaliczenia,
- kolizja,
- już ma grupę tego przedmiotu i typu,
- już zapisany albo już czeka,
- tura zamknięta,
- brak miejsc (UC5),
- pełna lista oczekujących.

„W połowie” nic się nie dzieje częściowo, bo wszystko jest jedną transakcją. Jeśli cokolwiek się
nie powiedzie, nic nie zostaje zapisane.

### E4. Model danych i schemat SQL

**P: Po co licznik `enrolled_count`, skoro można policzyć `COUNT(*)` z `enrollment`? To łamie
normalizację.**
O: Tak, to świadoma denormalizacja. Dzięki licznikowi sprawdzenie limitu i zajęcie miejsca to
**jedna atomowa instrukcja**:
`UPDATE section SET enrolled_count = enrolled_count + 1 WHERE id = ? AND enrolled_count < capacity`.
Z `COUNT(*)` trzeba by najpierw policzyć, a potem wstawić, czyli dokładnie błąd *check-then-act*
z wersji naiwnej. Ryzyko denormalizacji (licznik rozjedzie się z rzeczywistością) kontrolujemy
w trzech miejscach:
- licznik zmienia tylko EnrollmentService,
- `CHECK` pilnuje, żeby licznik nie przekroczył limitu,
- widok `section_invariant_violations` wykrywa rozjazd, a worker sprawdza go okresowo.

Dopytanie, „ale sam `CHECK` przecież wystarczy?”: nie, i scenariusz 1 to pokazuje. Wersja
naiwna zapisała 30 osób, a licznik wynosi 1. `CHECK (1 <= 10)` jest spełniony. `CHECK` chroni
wartość licznika, a nie jego zgodność z liczbą wierszy. Do tego potrzebny jest audyt.

**P: Dlaczego `VARCHAR` z `CHECK` zamiast typu `ENUM`?**
O: Dodanie wartości do `ENUM` w PostgreSQL wymaga `ALTER TYPE` i ma ograniczenia, np. dawniej
nie dało się tego zrobić w transakcji, a usunąć wartości nie można w ogóle. `CHECK` łatwo zmienić
migracją. ORM i inne narzędzia też lepiej znoszą zwykłe napisy. Kosztem jest kilka bajtów więcej
na wiersz, co przy naszej skali nie ma znaczenia.

**P: Dlaczego klucze sztuczne (`BIGSERIAL`), a nie naturalne, np. kod kursu?**
O: Kody zmieniają się w czasie (przemianowanie przedmiotu, nowy program studiów), a klucz główny
powinien być stały, bo odwołują się do niego klucze obce. Kody naturalne mają `UNIQUE`, więc
nadal są unikalne. Wyjątek: `completed_course` ma klucz złożony (student, kurs, semestr), bo to
naturalna tożsamość wpisu i nic się do niego nie odwołuje.

**P: Dlaczego `app_user` plus osobne `student` i `lecturer`?**
O: To dziedziczenie w modelu tabela-na-podtyp. Wspólne dane (e-mail, hasło, imię, rola) są raz,
a dane specyficzne (numer indeksu, kierunek, katedra) w tabelach podtypów. Klucz `user_id` jest
jednocześnie główny i obcy. Klucze obce mogą wskazywać dokładnie tam, gdzie trzeba: zapis
wskazuje na `student`, więc nie da się zapisać prowadzącego na zajęcia. Powiadomienie wskazuje
na `app_user`, bo może trafić do każdego.
Dopytanie, „co z osobą, która jest i doktorantem, i prowadzącym?”: model na to pozwala, bo
ten sam `user_id` może być w obu tabelach. Pole `role` przechowuje jednak jedną rolę, więc do
takich przypadków trzeba by je zamienić na tabelę ról. To znane uproszczenie.

**P: Dlaczego zapis i lista oczekujących to dwie tabele, a nie jedna ze statusem WAITING?**
O: Mają inny cykl życia i inne reguły:
- **Statusy:** zapis jest ENROLLED albo DROPPED. Wpis na liście ma pięć stanów, powód pominięcia
  i powiązanie z zapisem po awansie.
- **Limity:** liczba zapisów liczy się do limitu grupy, a liczba oczekujących do `waitlist_limit`.

Połączenie tego w jedną tabelę dałoby wiele kolumn używanych tylko w części wierszy i trudniejsze
ograniczenia. Teraz każde z nich jest prostym `CHECK` albo indeksem częściowym.

**P: Co to jest indeks częściowy i po co?**
O: To indeks tylko na wierszach spełniających warunek, np.
`UNIQUE (student_id, section_id) WHERE status = 'ENROLLED'`. Pozwala trzymać historię (wiele
wpisów DROPPED tej samej osoby w tej samej grupie), a jednocześnie gwarantuje, że **aktywny**
zapis jest tylko jeden. Zwykły `UNIQUE` zabroniłby ponownego zapisu po wypisie.
Dopytanie, „to po co jeszcze jawne sprawdzenie w kodzie?”: żeby dać studentowi czytelny
komunikat („już zapisany do tej grupy”) zamiast błędu bazy. Indeks to ostatnia linia obrony,
a każdy pilnuje tylko jednej tabeli. Nie wyłapie np. sytuacji „zapisany i jednocześnie czeka”,
to robi kod i widok audytu.

**P: Dlaczego kolejność na liście to `id`, a nie `created_at` albo kolumna „pozycja”?**
O:
- **Kolumna „pozycja”:** przy każdej rezygnacji trzeba by przenumerować wszystkich za nią.
  To dużo zapisów i ryzyko błędu.
- **`created_at` z domyślnym `now()`:** w PostgreSQL to czas **początku transakcji**, a nie
  wstawienia. Transakcja, która zaczęła się wcześniej, ale czekała na blokadę, dostałaby
  wcześniejszy czas niż ktoś, kto był przed nią na liście.
- **`id` z sekwencji:** jest nadawane w chwili `INSERT`, a ten dzieje się pod blokadą grupy,
  więc kolejność `id` to kolejność dopisania.

Pozycję do wyświetlenia liczymy jako liczbę wpisów WAITING z mniejszym `id` plus jeden.
Dopytanie, „sekwencje mają dziury, czy to problem?”: nie, liczy się tylko porządek, a nie
ciągłość numerów.

**P: Jak liczycie parzystość tygodni?**
O: Od `term.starts_on`: tydzień 1 (nieparzysty) to tydzień kalendarzowy, w którym wypada
początek semestru. Kolejne tygodnie są na przemian parzyste i nieparzyste. To znane uproszczenie:
przerwa świąteczna i dni wolne potrafią przesunąć cykl, a tego jeszcze nie modelujemy (patrz F).

**P: Dlaczego `passed` jest wyliczane, a nie wpisywane?**
O: Żeby nie dało się zapisać sprzecznych danych typu „ocena 2.0 i zaliczone”. Kolumna
`GENERATED ALWAYS AS (grade >= 3.0) STORED` zawsze zgadza się z oceną. Ocena ma `CHECK` na
dozwolone wartości (2.0, 3.0, 3.5, 4.0, 4.5, 5.0).
Dopytanie, „a przedmioty na zaliczenie bez oceny?”: tego model jeszcze nie obsługuje,
bo `grade` jest wymagane. To znany brak (patrz F).

**P: Po co trigger na cykle wymagań? `CHECK` nie wystarczy?**
O: `CHECK (course_id <> required_course_id)` łapie tylko pętlę A → A. Cykl A → B → A wymaga
przejścia po grafie, czego `CHECK` nie umie, bo patrzy tylko na jeden wiersz. Trigger robi to
rekurencyjnym `WITH RECURSIVE` przed wstawieniem. Bez tego nikt nie mógłby zapisać się na żaden
z kursów w cyklu. Sprawdziliśmy na PostgreSQL 16: wstawienie zamykające cykl jest odrzucane.

**P: Po co tury zapisów jako osobna tabela? Nie wystarczy data otwarcia w semestrze?**
O: W semestrze bywa kilka tur, np. tura 1 tylko dla swojego kierunku, tura 2 dla wszystkich.
- **Status, a nie same daty:** o możliwości zapisu decyduje `status`, bo dziekanat może turę
  otworzyć lub przedłużyć ręcznie, np. po awarii. Godziny `opens_at` i `closes_at` to tylko
  harmonogram dla workera.
- **Jedna otwarta tura:** indeks częściowy `UNIQUE (term_id) WHERE status = 'OPEN'` gwarantuje,
  że w semestrze otwarta jest najwyżej jedna tura.

**P: Gdzie jest pilnowane, że limit grupy nie przekracza liczby miejsc w sali?**
O: W CatalogService, a nie w bazie. Sala jest przypisana do **terminu** (`meeting`), a nie do
grupy, bo grupa może mieć różne terminy w różnych salach. Ograniczenie „limit ≤ najmniejsza sala
spośród terminów grupy” obejmuje wiele tabel, a `CHECK` widzi tylko jeden wiersz. Dałoby się to
zrobić triggerem i jest to kandydat na etap 3.

**P: Dlaczego sala jest przy terminie, a nie przy grupie?**
O: Bo grupa może mieć np. wykład w poniedziałek w auli, a w środę w mniejszej sali. Kolizje sal
też liczy się per termin.

**P: Jak sprawdzacie kolizję? Pokażcie warunek.**
O: Dwa terminy kolidują, gdy spełnione są wszystkie cztery warunki:
- **Ten sam semestr.**
- **Ten sam dzień tygodnia.**
- **Przedziały godzin się przecinają:** `start1 < end2 AND start2 < end1`. Ostre nierówności
  sprawiają, że zajęcia 9:30–11:00 nie kolidują z 8:00–9:30.
- **Tygodnie się pokrywają:** ALL koliduje ze wszystkim, ODD tylko z ODD, EVEN tylko z EVEN.

To funkcja SQL `schedule_conflicts(student, grupa)`. Zwraca **listę** kolidujących grup, żeby
pokazać studentowi, z czym jest kolizja.
Dopytanie, „a przerwa na przejście między budynkami?”: tego nie modelujemy. Można by dodać
minimalny odstęp, ale wymaganie mówi o kolizjach, a nie o logistyce.

**P: Dlaczego reguły biorą pod uwagę tylko bieżący semestr?**
O: Zapis zostaje w stanie ENROLLED także po końcu semestru, bo to historia. Bez warunku na
semestr zeszłoroczny zapis na IO blokowałby powtarzanie IO („masz już laboratorium z IO”),
a zeszłoroczne zajęcia dawałyby kolizje. Sprawdziliśmy to na PostgreSQL 16.

**P: Dlaczego `TIMESTAMPTZ`, a godziny zajęć to `TIME` bez strefy?**
O: `TIMESTAMPTZ` to konkretne chwile (zapis, otwarcie tury), które muszą być jednoznaczne, także
przy zmianie czasu. Godzina zajęć „10:00 w poniedziałek” to godzina lokalna, która ma zostać
10:00 także po zmianie czasu na zimowy, więc strefa byłaby tu błędem.

**P: Co się dzieje przy usuwaniu kursu albo grupy?**
O: `ON DELETE CASCADE` jest tylko tam, gdzie dane podrzędne nie mają sensu bez nadrzędnych:
terminy i prowadzący grupy, wymagania kursu. Zapisów i list nie kasujemy kaskadowo: klucz obcy
zablokuje usunięcie grupy, w której ktoś jest lub był zapisany, bo to historia studenta.

### E5. Współbieżność i blokady (tu będzie najwięcej pytań)

**P: Na czym dokładnie polega błąd w wersji naiwnej?**
O: To *check-then-act* połączone z *lost update*:
1. Trzydzieści wątków odczytuje `enrolled_count = 0`.
2. Każdy widzi, że jest miejsce, i wstawia zapis.
3. Każdy ustawia licznik na „swoje 0 + 1”, czyli 1, nadpisując pozostałych.

Wynik: 30 wierszy zapisu i licznik 1.
Dopytanie, „wstawiliście `sleep`, więc to sztuczny przykład”: `sleep(0.01)` tylko poszerza
okno, żeby błąd był widoczny za każdym razem. Bez niego błąd też istnieje, tylko pojawia się
rzadziej, a to gorzej, bo przechodzi testy i wychodzi na produkcji przy otwarciu tury.

**P: Skoro warunkowy `UPDATE` jest atomowy, po co jeszcze `SELECT ... FOR UPDATE` na grupie?**
O: Sam `UPDATE` z warunkiem chroni **licznik**. Sprawdziliśmy to na PostgreSQL: druga sesja
czeka na pierwszą, po jej zatwierdzeniu ponownie sprawdza warunek i nic nie zmienia. Ale decyzja
o zapisie to kilka instrukcji, a nie jedna. Przykład bez blokady grupy:
1. Student A dostaje „0 wierszy”, bo grupa jest pełna, i zamierza dopisać się na listę.
2. W tym czasie student B się wypisuje, a awans z listy widzi pustą listę i nikogo nie zapisuje.
3. A dopisuje się na listę.

Teraz A czeka przy wolnym miejscu, a niezmiennik jest złamany. Blokada wiersza grupy sprawia, że
wypis B czeka na koniec transakcji A, więc awans zobaczy A na liście. Blokada pilnuje też
`waitlist_limit` (policzenie oczekujących i dopisanie to dwie instrukcje) i kolejności `id` na
liście.

**P: Po co blokada wiersza studenta?**
O: Reguły kolizji i „jednej grupy danego typu” dotyczą **całego planu** studenta, a nie jednej
grupy. Jeśli student wyśle naraz zapis do L03 i L05 z jednego przedmiotu (dwie karty
przeglądarki), to blokady grup są różne. Obie transakcje sprawdzą plan, zanim którakolwiek go
zmieni, i student skończy z dwoma laboratoriami albo z kolizją. Blokada wiersza studenta ustawia
jego zapisy w kolejce.
Dopytanie, „czemu nie `pg_advisory_xact_lock(student_id)`?”: działa równoważnie. Blokada
wiersza jest bardziej naturalna: widać ją w `pg_locks` jako blokadę konkretnego wiersza i nie
trzeba pilnować przestrzeni numerów blokad doradczych.

**P: Dlaczego najpierw student, potem grupa?**
O: Stała kolejność blokad zapobiega zakleszczeniom. Gdyby jeden zapis blokował grupę, a potem
studenta, a drugi odwrotnie, mogłyby czekać na siebie nawzajem. Wybraliśmy student → grupa, bo
student jest znany od razu z żądania, a jego blokada jest „tańsza” (dotyczy tylko jego).

**P: Ale awans z listy blokuje w odwrotnej kolejności. Czy to nie zakleszczenie?**
O: Tak, i to właśnie znaleźliśmy. Wypis trzyma blokadę grupy, a awans potrzebuje blokady
studenta B, żeby jego plan był stały w czasie sprawdzania kolizji. Jeśli B w tej chwili zapisuje
się do tej samej grupy (trzyma siebie, czeka na grupę), mamy zakleszczenie. Sprawdziliśmy na
PostgreSQL 16: `deadlock detected`. Rozwiązanie: `SELECT ... FOR UPDATE NOWAIT` na studencie B.
Jeśli jest zajęty, od razu błąd 55P03, wycofanie całej transakcji i ponowienie po chwili.
Dopytanie, „dlaczego nie pominąć B i wziąć następnego?”: B straciłby kolejkę tylko dlatego,
że akurat klikał coś innego. To niesprawiedliwe i trudne do wytłumaczenia studentowi.
Dopytanie, „czemu nie zablokować B najpierw?”: nie wiemy, kto jest B, dopóki nie zajrzymy na
listę, a listę trzeba czytać pod blokadą grupy. Kolejność wynika z logiki.
Dopytanie, „a jeśli ponowienia nie skończą się sukcesem?”: limit kilku prób z rosnącym
odstępem, potem błąd „spróbuj ponownie” dla użytkownika. Konflikt trwa milisekundy, więc w
praktyce druga próba przejdzie. To opis z `schemat.sql`, jeszcze nie kod.
Dopytanie, „czy PostgreSQL sam nie wykryje zakleszczenia?”: wykryje, ale po
`deadlock_timeout` (domyślnie 1 s) i przerwie losową z dwóch transakcji. `NOWAIT` daje
natychmiastową, przewidywalną reakcję. Błąd 40P01 i tak obsługujemy ponowieniem, jako
zabezpieczenie.

**P: Dlaczego nie poziom izolacji SERIALIZABLE? Załatwiłby wszystko.**
O: Zapewniłby poprawność, ale przy otwarciu tury setki transakcji o te same wiersze kończyłyby
się błędem serializacji (40001) i musiałyby być ponawiane. Przy dużej rywalizacji to fala
ponowień, które znowu się kłócą. `FOR UPDATE` ustawia transakcje w kolejce zamiast je przerywać,
więc zachowanie przy obciążeniu jest przewidywalne. 40001 obsługujemy na wszelki wypadek.

**P: Dlaczego prototyp jest na SQLite, skoro docelowo PostgreSQL?**
O: Żeby uruchamiał się wszędzie jednym poleceniem, bez instalowania bazy, także u prowadzącego
i u grupy, która przejmie projekt. Prototyp sprawdza **logikę**: atomowe zajęcie miejsca, awans
w jednej transakcji, ponowne sprawdzanie reguł, niezmienniki. Ograniczenie mówimy wprost: SQLite
z `BEGIN IMMEDIATE` blokuje całą bazę, więc prototyp nie sprawdza blokad pojedynczych wierszy ani
wydajności. To sprawdzamy osobno na PostgreSQL. Zakleszczenie przy awansie i `NOWAIT` już
sprawdziliśmy.

**P: Skoro SQLite blokuje całą bazę, to wersja bezpieczna działa „bo i tak wszystko jest
po kolei”. Co to dowodzi?**
O: Dobra uwaga. Scenariusz 1 dowodzi, że **samo opakowanie w transakcję nie wystarczy**: wersja
naiwna też ma `BEGIN IMMEDIATE`, ale odczytuje licznik **przed** transakcją. Pokazuje więc, że
sprawdzenie i zajęcie miejsca muszą być w tej samej atomowej operacji. Na PostgreSQL ten sam
warunkowy `UPDATE` sprawdziliśmy na dwóch sesjach i też nie przepuścił dwóch osób na jedno
miejsce. Scenariusze 4–6 dowodzą poprawności logiki listy (kolejność, pomijanie, wygaszanie),
a ta od rodzaju blokady nie zależy.

**P: Jak dokładnie testujecie równoległość w prototypie?**
O: Każdy wątek ma osobne połączenie z bazą. `threading.Barrier` wstrzymuje wszystkie wątki,
aż każdy będzie gotowy, i dopiero wtedy puszcza je naraz. Dzięki temu żądania naprawdę się
nakładają, a nie idą jedno po drugim. Po scenariuszu sprawdzamy wynik asercjami i funkcją
`check_invariants`.

**P: Jakie niezmienniki sprawdzacie?**
O:
1. Licznik w grupie równa się liczbie zapisów ENROLLED.
2. Licznik nie przekracza limitu.
3. Nikt nie czeka na liście, gdy w grupie są wolne miejsca.
4. Nikt nie jest jednocześnie zapisany i oczekujący w tej samej grupie.
5. Nikt nie czeka na grupę przedmiotu, z którego ma już grupę tego samego typu.

W PostgreSQL niezmienniki 1, 3 i 4 sprawdza widok `section_invariant_violations`, a niezmiennik 2
pilnuje `CHECK (enrolled_count <= capacity)`.

### E6. Lista oczekujących

**P: Co, jeśli student z listy już nie chce tej grupy? Zapisujecie go bez pytania.**
O: Temat wprost wymaga „automatycznego zapisywania, gdy zwolni się miejsce”. Dopisując się na
listę, student wyraża zgodę na zapis. Do tego:
- może w każdej chwili zrezygnować z listy (UC7),
- po zapisie może się wypisać (UC6), a jego miejsce dostaje następny,
- dostaje powiadomienie,
- zapis na inną grupę tego samego przedmiotu i typu automatycznie anuluje jego wpisy na innych
  listach (z ostrzeżeniem w interfejsie),
- po zamknięciu tury listy wygasają, więc nikt nie zostanie zapisany niespodziewanie po turze.

Dopytanie, „a model z ofertą do potwierdzenia w ciągu np. 24 h?”: rozważaliśmy go. Jest
łagodniejszy dla studenta, ale miejsce stoi puste w czasie oczekiwania, potrzebne są timery
i wygasanie ofert, a przy końcu tury ktoś może nie zdążyć. Wymaganie mówi o automacie, więc
wybraliśmy prostszy, natychmiastowy wariant.

**P: Dlaczego osoba z kolizją jest pomijana (SKIPPED), a nie zostaje na liście?**
O: Gdyby została na początku listy, blokowałaby awans wszystkich za nią, bo nie da się jej
zapisać. Pomijamy ją tylko wtedy, **gdy jest wolne miejsce**. Bez miejsca nikogo nie ruszamy, bo
student może jeszcze usunąć kolizję. Pominięty dostaje powiadomienie z powodem i może dopisać
się ponownie (na koniec).
Dopytanie, „traci kolejkę za coś, co mógł zaraz poprawić?”: tak. Kolizję spowodował jednak
sam, zapisując się na zajęcia w tym samym terminie, a system ostrzega go o tym w interfejsie.
Alternatywą jest zachowanie pozycji i pomijanie przy każdym awansie. To bardziej skomplikowane
i bez jasnego końca.

**P: Po co ponownie sprawdzać wymagania przy awansie, skoro sprawdzono je przy dopisaniu?**
O: Od dopisania do awansu mogą minąć dni, a stan się zmienia:
- student mógł zapisać się na zajęcia w tym samym terminie (kolizja),
- mógł dostać inną grupę tego przedmiotu,
- dziekanat mógł poprawić ocenę (UC15), więc przedmiot wstępny przestał być zaliczony.

Zapis z listy musi spełniać te same reguły, co zwykły zapis.

**P: Co się dzieje, gdy dwóch studentów wypisze się w tej samej chwili?**
O: Obie transakcje potrzebują blokady grupy, więc wykonują się po kolei. Pierwsza zapisuje
pierwszego z listy, druga, już po zatwierdzeniu pierwszej, widzi go jako PROMOTED i zapisuje
drugiego. Prototyp to sprawdza (scenariusz 4): awansowali dokładnie dwaj pierwsi z listy,
a kolejność zapisów zgadza się z kolejnością na liście. Sprawdzamy to w bazie, a nie w kolejności
wypisania wyników przez wątki.

**P: Co robi zwiększenie limitu?**
O: W tej samej transakcji zwiększa `capacity` i uruchamia awans, który zapisuje tylu
oczekujących, ile jest nowych miejsc. Zmniejszenie poniżej liczby zapisanych blokuje `CHECK`,
co sprawdziliśmy na PostgreSQL. Nikogo nie wypisujemy automatycznie.

**P: Dziekanat zapisuje studenta do pełnej grupy. Co z kolejką?**
O: Zapis przez dziekanat do pełnej grupy zwiększa limit o 1 w tej samej transakcji, nie ponad
liczbę miejsc w sali. Kolejka nie traci więc miejsca: oczekujący nadal czekają na to, na co
czekali. Gdybyśmy zamiast tego zapisali ponad limit bez jego zmiany, złamalibyśmy `CHECK`.
Gdybyśmy zabrali miejsce z puli, ukradlibyśmy je pierwszemu z listy. Scenariusz 6: Ewa
zapisana, L07 ma 3/3, Kuba nadal czeka.
Dopytanie, „dziekanat może pominąć kolizje?”: nie. Może pominąć wymagania wstępne i działać
poza turą, ale kolizje i regułę jednej grupy danego typu sprawdzamy zawsze, bo wynikają z fizyki
(nie da się być w dwóch salach naraz).

**P: Po co wygaszanie list przy zamknięciu tury (EXPIRED)?**
O: Bez tego wypis przez dziekanat w listopadzie zapisałby automatycznie kogoś, kto od dawna ma
inny plan i nawet nie pamięta, że był na liście. Po turze zmiany robi dziekanat ręcznie.
Studenci dostają powiadomienie, że lista wygasła.

**P: Dlaczego zapis na L05 anuluje czekanie na L03?**
O: Po zapisie na L05 student i tak zostałby pominięty przy awansie na L03, bo miałby dwa
laboratoria z jednego przedmiotu. Jego wpis tylko zajmowałby miejsce na liście
(`waitlist_limit`) innym i dawał im fałszywą pozycję. Interfejs ostrzega przed tym przy
przycisku „Zapisz”.
Dopytanie, „a jeśli student woli L03 i chce na nią czekać, mając L05?”: to zamiana grupy
i świadomie jej nie obsługujemy. To kandydat na etap 3: atomowe „wypisz z L05 i zapisz na L03,
gdy zwolni się miejsce”.

**P: Jak działa limit długości listy?**
O: `section.waitlist_limit` (domyślnie 50). Przy braku miejsc liczymy wpisy WAITING pod blokadą
grupy. Jeśli limit jest osiągnięty, odmowa „brak miejsc i pełna lista oczekujących”. Po co:
bardzo długa lista daje złudną nadzieję, a pozycja 200 w praktyce oznacza „nie dostaniesz się”.

### E7. Wymagania wstępne

**P: Jak sprawdzacie wymagania wstępne?**
O: Dla kursu grupy bierzemy wszystkie kursy wymagane (`course_prerequisite`) i szukamy tych, dla
których student **nie ma** wpisu `completed_course` z `passed = true`. Pusta lista oznacza, że
wymagania są spełnione. Niepusta lista to odmowa z podaniem brakujących przedmiotów.
Dopytanie, „a jeśli student zdał przedmiot za drugim razem?”: klucz `completed_course` to
(student, kurs, semestr), więc są oba wpisy, a wystarczy jeden zaliczony.

**P: Co z wymaganiami typu „A lub B”, przedmiotami równoważnymi albo „w trakcie realizacji”?**
O: Obecny model obsługuje tylko koniunkcję: trzeba zaliczyć wszystkie wymagane. To świadome
uproszczenie zgodne z tematem („zaliczone przedmioty”). Rozszerzenie: grupy alternatyw
(`prerequisite_group` z warunkiem „jeden z”) albo tabela równoważności kursów. Zapisaliśmy to
jako znany brak.

**P: Skąd system wie, co student zaliczył?**
O: Z importu ocen (UC15, `StudentRecordsService`), np. z eksportu systemu ocen. Nie projektujemy
wystawiania ocen, bo to poza tematem.

### E8. Prototyp

**P: Ile scenariuszy ma prototyp i co każdy sprawdza?**
O: Sześć:
1. Wyścig 30 na 10: wersja naiwna kontra bezpieczna.
2. Wymagania wstępne: ocena 4.5 kontra 2.0.
3. Kolizje: pięć przypadków (nakładanie, styk, inny dzień, parzystość, co tydzień).
4. Lista oczekujących:
   - bez miejsca nikt nie awansuje,
   - pominięcie osoby z kolizją,
   - zwiększenie limitu,
   - dwa równoczesne wypisy,
   - powiadomienia.
5. Jedna grupa danego typu, limit listy, ponowny zapis i anulowanie wpisu na innej liście.
6. Dziekanat: zapis bez wymagań i ponad limit, zamknięcie tury, wypis po turze.

Szczegóły są w `notes.md`.

**P: Czym prototyp różni się od docelowego schematu?**
O: Celowo jest uproszczony:
- **Silnik:** SQLite zamiast PostgreSQL. Blokada całej bazy zamiast wierszy, brak `NOWAIT`
  i ponowień.
- **Brak tabel:** nie ma semestrów i sal. Jest jedna tura bez harmonogramu, a `find_conflicts`
  nie filtruje po semestrze.
- **Powiadomienia:** `notification` ma `student_id` i tekst zamiast `user_id` i `JSONB`.
- **Statusy:** nie ma `resolved_at` ani dat.

Reguły i przebieg transakcji są takie same, jak opisane w `schemat.sql`.

**P: Czy prototyp to kod, który wejdzie do systemu?**
O: Nie, to prototyp do wyrzucenia, ale jego wiedza zostaje. Zostaną przebieg transakcji
i reguły, a `check_invariants` przeniesiemy jako test regresyjny i audyt.

### E9. Mock-up i interfejs

**P: Dlaczego mock-up tylko dla studenta?**
O: To najczęstszy i najbardziej obciążony ekran, na którym widać wszystkie wymagania tematu
naraz: miejsca, wymagania, kolizje, listę i plan. Ekrany dziekanatu to głównie formularze CRUD,
mniej ryzykowne.

**P: Skąd student wie, ile osób jest przed nim na liście? Czy liczba miejsc się odświeża?**
O: Pozycja to liczba wpisów WAITING z mniejszym `id` plus jeden. W mock-upie widać „miejsce
2 z 4”. Odświeżanie: na razie przy przeładowaniu lub co kilka sekund. Push (SSE albo WebSocket)
to możliwe rozszerzenie. Ostateczną decyzję i tak podejmuje serwer w transakcji, więc nieaktualny
licznik na ekranie niczego nie psuje: najwyżej zamiast zapisu student trafi na listę.

**P: Przycisk jest zablokowany przy kolizji. Czy to nie wystarczy, po co sprawdzać na serwerze?**
O: Interfejs to tylko wygoda. Żądanie można wysłać z pominięciem przycisku (inna karta, skrypt,
narzędzia przeglądarki), a stan mógł się zmienić od wyświetlenia strony. Reguły zawsze sprawdza
serwer w transakcji.

### E10. Pytania „a co, jeśli…”

**P: Co, jeśli worker padnie?**
O: Zapisy i awanse działają dalej, bo są w API i w transakcjach. Opóźnią się:
- e-maile: zostają w outboxie, `sent_at IS NULL`, i wyjdą po restarcie,
- automatyczne otwarcie i zamknięcie tury: dziekanat może to zrobić ręcznie (UC16).

Dopytanie, „a dwa workery naraz?”: wysyłkę można bezpiecznie zrównoleglić przez
`FOR UPDATE SKIP LOCKED` na outboxie. Zmiana statusu tury jest idempotentna, a indeks dopuszcza
tylko jedną otwartą turę.

**P: Czy e-mail może przyjść dwa razy?**
O: Tak, wysyłka z outboxa jest „co najmniej raz”. Jeśli worker wyśle e-mail i padnie przed
ustawieniem `sent_at`, po restarcie wyśle go ponownie. Dla powiadomień to akceptowalne:
duplikat jest mniej szkodliwy niż zgubiona informacja. Powiadomienie w aplikacji jest jedno,
bo to wiersz w bazie.

**P: Co, jeśli baza padnie w trakcie zapisu?**
O: Transakcja jest atomowa: albo zapis, licznik i powiadomienie wejdą razem, albo nic. Student
dostanie błąd i może ponowić. Indeks częściowy zapobiega podwójnemu zapisowi przy ponowieniu.

**P: Co, jeśli student ma dwie karty i klika „zapisz” w obu?**
O: Do tej samej grupy pierwsza transakcja go zapisze, druga dostanie „już zapisany do tej grupy”.
Do dwóch grup tego samego przedmiotu blokada wiersza studenta ustawi je w kolejce: pierwsza
zapisze, druga odmówi z powodu „już zapisany do grupy L05 tego przedmiotu”.

**P: Jak zapewniacie sprawiedliwość? Kto ma szybszy internet, ten wygrywa.**
O: Model to „kto pierwszy, ten lepszy”, bo tak jest w temacie i tak działają typowe zapisy.
Narzędzia, które już mamy w modelu:
- **Tury zapisów:** np. tura 1 tylko dla danego kierunku.
- **Limit żądań:** wyrównuje szanse z botami.
- **Listy oczekujących:** dają drugą szansę.

Loteria albo priorytety (rok, średnia) to możliwe rozszerzenie. Zmieniłoby głównie sposób
przydziału w chwili otwarcia, a nie model danych.

**P: Czy student ma limit ECTS albo liczby godzin?**
O: Nie, tego nie ma w temacie. Dodanie byłoby kolejną regułą w `check_rules` (suma ECTS zapisów
w semestrze ≤ limit), sprawdzaną pod blokadą studenta. Dlatego blokada studenta jest i tak
potrzebna.

---

## F. Słabe punkty, które znamy – i co odpowiadamy

Lepiej przyznać się samemu niż dać się złapać. Każdy punkt ma gotową odpowiedź „co z tym zrobimy”.

1. **Kolizje sal i prowadzących są tylko opisane.** Są w UC12 (`include` UC4), ale nie ma
   funkcji SQL ani scenariusza prototypu. Reguła jest ta sama, co dla studenta, tylko
   grupowana po `room_id` albo `lecturer_id` zamiast `student_id`. Plan na etap 3.
2. **Limit grupy względem miejsc w sali pilnuje kod, a nie baza.** Powód: sala jest przy terminie,
   a ograniczenie obejmuje wiele tabel. Możliwy trigger.
3. **Parzystość tygodni bez kalendarza.** Liczymy ją od `term.starts_on`, a przerwy (święta, dni
   rektorskie) przesuwają cykl. Rozwiązanie: tabela tygodni semestru z numerem i parzystością
   albo konkretne daty zajęć.
4. **Wymagania wstępne to tylko koniunkcja.** Nie ma alternatyw („A lub B”), równoważników,
   „w trakcie realizacji” ani minimalnej oceny.
5. **Brak zaliczeń bez oceny** („zal”), bo `grade` jest wymagane.
6. **Brak zamiany grupy.** Zapis na L05 anuluje czekanie na L03, więc nie da się czekać na
   lepszą grupę, mając już gorszą.
7. **Pominięty (SKIPPED) traci kolejkę na stałe.** To świadoma decyzja, ale da się ją podważyć.
8. **Prototyp ≠ docelowy schemat.** SQLite blokuje całą bazę, nie ma semestrów i sal,
   powiadomienia są uproszczone. `NOWAIT` i ponawianie istnieją tylko w opisie i w ręcznym teście
   na PostgreSQL, a nie w kodzie.
9. **Brak pomiarów wydajności.** Liczby o czasie oczekiwania to szacunki.
10. **Brak śladu, kto z dziekanatu wykonał operację.** `source = 'ADMIN'` mówi, że to decyzja
    dziekanatu, ale nie który pracownik. Do dodania kolumna `created_by` albo dziennik audytu.
    Ważne też ze względu na RODO.
11. **`app_user.role` to jedna rola.** Doktorant prowadzący zajęcia wymagałby tabeli ról.
12. **E-maile mogą się zdublować** (wysyłka „co najmniej raz”).
13. **Notacja:** UC3 i UC4 jako osobne przypadki można nazwać dekompozycją funkcjonalną.
    Uzasadnienie (współdzielenie) jest w E3.
14. **„Kto pierwszy, ten lepszy” premiuje szybkie łącze.** Łagodzą to tury i limit żądań.
15. **Możliwa optymalizacja blokad.** Zamiast `FOR UPDATE` na studencie lepiej użyć
    `FOR NO KEY UPDATE`. Nie blokuje wtedy wstawiania wierszy, które tylko wskazują studenta
    kluczem obcym (np. import ocen w trakcie zapisów). Na razie jest `FOR UPDATE`, bo to
    prostsze do wytłumaczenia.

---

## G. Ściąga – liczby, nazwy, fakty

- **Etapy:** etap 2 to 21.X i 30% oceny projektu. Etap 3 (projekt wstępny: pełne UML, sekwencje,
  klasy z metodami) to 28.X.
- **Przypadki użycia:**
  - UC0: uwierzytelnienie,
  - UC1–UC9: student i system (UC9 to awans z listy),
  - UC10: prowadzący,
  - UC11–UC16: dziekanat,
  - UC17: zegar,
  - UC18: wygaszenie list.
- **Statusy:**
  - zapis: `ENROLLED`, `DROPPED`,
  - źródło zapisu: `DIRECT`, `WAITLIST`, `ADMIN`,
  - lista oczekujących: `WAITING`, `PROMOTED`, `SKIPPED`, `CANCELLED`, `EXPIRED`,
  - tura: `PLANNED`, `OPEN`, `CLOSED`,
  - typ grupy: `LECTURE`, `EXERCISE`, `LAB`, `SEMINAR`,
  - parzystość: `ALL`, `ODD`, `EVEN`.
- **Kody błędów PostgreSQL:** 55P03 (nie można uzyskać blokady, `NOWAIT`), 40P01 (zakleszczenie),
  40001 (błąd serializacji). Wszystkie trzy obsługujemy wycofaniem i ponowieniem.
- **Kluczowa instrukcja:**
  `UPDATE section SET enrolled_count = enrolled_count + 1 WHERE id = :s AND enrolled_count < capacity`.
  0 wierszy oznacza brak miejsc, więc student trafia na listę oczekujących.
- **Warunek kolizji:** ten sam semestr i dzień, `start1 < end2 AND start2 < end1`, tygodnie się
  pokrywają.
- **Kolejność blokad:** zapis student → grupa. Awans: grupa → student B z `NOWAIT`.
- **Scenariusz 1:** naiwnie 30 zapisanych na 10 miejsc, licznik 1. Bezpiecznie 10 zapisanych
  i 20 na liście.
- **Scenariusz 4:** student 3 pominięty (kolizja z L05), student 4 awansował. Po zwiększeniu
  limitu awansował 5. Po dwóch równoczesnych wypisach awansowali 6 i 7.
- **Domyślny `waitlist_limit`:** 50.
- **Rozmiary grup w przykładach:** wykład 150, ćwiczenia 30, laboratorium 15.
- **Dodatkowe obiekty w schemacie:** funkcje `schedule_conflicts` i `same_course_kind_section`,
  widok `section_invariant_violations`, trigger `course_prerequisite_no_cycle`.
- **Pliki:**
  - wszystko jest opisane w `README.md`,
  - definicje tabel w `notes.md`,
  - regeneracja diagramów na końcu README (`er.py`: `python3 er.py && tectonic er.tex`).
