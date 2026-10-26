# Etap 3 (28.X) – skrypt prezentacji (maks. 7 minut)

Slajdy: `prezentacja/prezentacja_krotka.pdf` (12 slajdów: tytuł, 10 slajdów treści i „Dziękujemy”;
dalej slajdy zapasowe). Ten plik jest **jedynym źródłem tekstu** do wystąpienia –
`PREZENTACJA_OPIS.md` tylko do niego odsyła.

- **Mowa: 550 słów** (liczone `wc -w` na samych cytatach poniżej; Kamil 194, Bartosz 164,
  Krzysztof 192). Przy ok. 120 słowach na minutę to ok. 4:30 samej mowy. Z pauzami, wskazywaniem kroków na diagramach i zmianami osób wychodzi
  ok. **6:35**, więc zostaje ok. 25 s zapasu do limitu 7:00.
- **Podział:** Kamil ok. 2:15 (slajdy 0–3), Bartosz ok. 2:05 (4–6), Krzysztof ok. 2:15 (7–11).
  Zmiana osoby bez zapowiadania („teraz kolega…”) – od razu treść.
- Kolumna „do” to moment, w którym slajd ma się skończyć (te same czasy są w komentarzach
  `% N --- m:ss` w `prezentacja_krotka.tex`).
- Tekst nie musi być czytany słowo w słowo, ale **liczby i nazwy muszą zostać takie same** –
  każda jest sprawdzona w kodzie (tabela na końcu).

---

## Slajd 0 – Tytuł · Kamil · do 0:10

> Dzień dobry. System zapisów na zajęcia, etap trzeci: projekt wstępny systemu.

## Slajd 1 – Trzy decyzje etapu 3 · Kamil · do 0:45

> Od ostatniej prezentacji podjęliśmy trzy decyzje. Pierwsza: tury per kierunek. Dwadzieścia
> tysięcy studentów nie zapisuje się naraz, tylko kierunek po kierunku, co pół godziny, więc
> w szczycie jest około tysiąca osób. Druga: reguły biznesowe są w kodzie, jako czyste funkcje,
> a baza pilnuje spójności. Trzecia: projekt sprawdziliśmy działającą implementacją, więc
> diagramy opisują istniejący kod.

## Slajd 2 – Architektura i stos · Kamil · do 1:35

Wskazywać na diagramie od góry do dołu.

> Architektura. Aplikacja React w przeglądarce, nginx serwuje statykę i przekazuje żądania do API
> w FastAPI. API ma warstwy: HTTP sprawdza token i rolę, serwis prowadzi transakcję, domena
> podejmuje decyzję, a dane są w PostgreSQL. Obok działa worker: otwiera i zamyka tury, wysyła
> e-maile z outboxa i co minutę sprawdza niezmienniki. API jest bezstanowe, więc przy większym
> ruchu dokładamy instancje. Stos jest po prawej, a uzasadnienie każdego wyboru – w dokumentacji.

## Slajd 3 – Przypadki użycia (student) · Kamil · do 2:15

Wskazać UC2, potem strzałki `<<include>>` i `<<extend>>`.

> Przypadki użycia. Mamy ich dwadzieścia osiem, od UC0 do UC27, na dwóch diagramach; tu jest
> część studenta. Główny jest UC2, zapis do grupy. Zawsze dołącza sprawdzenie wymagań wstępnych,
> kolizji i uprawnienia, czyli czy trwa tura kierunku studenta. Gdy brak miejsc, rozszerza go
> dopisanie do listy oczekujących. W dokumentacji każdy przypadek wywoływany przez użytkownika ma
> endpoint i listę kodów błędów.

## Slajd 4 – Sekwencja: zapis do grupy · Bartosz · do 3:05

Wskazywać kroki 2, 4, ramkę `break` (7) i krok 8.

> Sekwencja zapisu. Najpierw kontrola ruchu: limit operacji na studenta i bramka; przy nadmiarze
> API po najwyżej dwóch sekundach odpowiada 503 z informacją, kiedy ponowić. W kroku czwartym blokujemy wiersz
> studenta i sprawdzamy reguły zależne od jego planu. Odmowa kończy operację: wycofanie i kod 409
> z powodem, na przykład kolizją z konkretną grupą. Dopiero w kroku ósmym blokujemy grupę
> i trzymamy tę blokadę krótko: decyzja o miejscu i zapis albo lista oczekujących.

## Slajd 5 – Sekwencja: wypis i awans z listy · Bartosz · do 3:45

Wskazać pętlę, krok 5 (`NOWAIT`) i ramkę `alt` z 55P03.

> Wypis i awans z listy to jedna transakcja, więc nikt spoza listy nie zajmie zwolnionego miejsca.
> Tu kolejność blokad jest odwrotna: trzymamy grupę i blokujemy oczekującego, w kroku piątym, bez
> czekania. Jeśli jest zajęty, wycofujemy całość i ponawiamy, a on nie traci kolejki. Kto nie
> spełnia już warunków, dostaje status pominięty z powodem i powiadomienie.

## Slajd 6 – Pozostałe diagramy sekwencji · Bartosz · do 4:20

> Diagramów sekwencji jest siedem. Pozostałe pięć to: worker z turami i wysyłką e-maili, decyzje
> dziekanatu, układanie harmonogramu z kolizjami sal i prowadzących, wymagania wstępne
> z wykrywaniem cykli razem z importem ocen oraz logowanie. Wszystkie są w slajdach zapasowych.

## Slajd 7 – Projekt klas · Krzysztof · do 4:55

Wskazać `check_student`, potem `decide_seat`.

> Projekt klas na przykładzie zapisu. Serwis wywołuje dwie funkcje domeny. check_student dostaje
> stan studenta i grupę, a zwraca listę powodów odmowy. decide_seat dostaje stan miejsc i zwraca
> decyzję: zapis, lista albo, dla dziekanatu, zapis ponad limit, ale nie ponad salę. Te dwa kroki
> odpowiadają dwóm blokadom z sekwencji. Trzy pełne diagramy klas mają typy parametrów i opis
> każdej metody.

## Slajd 8 – Model danych (ER) · Krzysztof · do 5:20

Wskazać `program` i `round_program`.

> Model danych ma piętnaście tabel. Nowe są kierunek i powiązanie tury z kierunkami. Użytkownicy
> są w jednej tabeli z rolą. Ograniczenia w bazie zostały jako siatka bezpieczeństwa: przy
> refaktoryzacji odrzuciły jedenasty zapis na dziesięć miejsc.

## Slajd 9 – Uprawnienia ról i obsługa błędów · Krzysztof · do 5:50

> Uprawnienia: student działa tylko na swoich danych, bo identyfikator bierzemy z tokenu,
> prowadzący widzi listy swoich grup, a dziekanat zarządza resztą. Błędy mają jeden format: kod,
> komunikat i szczegóły. Odmowa to 409 z powodem, przeciążenie to 429 albo 503, a przeglądarka
> sama ponawia.

## Slajd 10 – Weryfikacja: testy i duży ruch · Krzysztof · do 6:30

> Weryfikacja. Trzydzieści pięć testów na prawdziwym PostgreSQL przechodzi, w tym wyścig o ostatnie
> miejsca. Test obciążeniowy: tysiąc studentów jednego kierunku naraz. Po poprawkach dziewięćdziesiąt
> pięć procent zapisów trwa poniżej dwóch sekund, bez ponowień. Przy trzech kierunkach naraz
> system zwalnia, ale nie przepełnia żadnej grupy. Dlatego tury per kierunek są konieczne.

## Slajd 11 – Pytania · Krzysztof · do 6:35

> Dziękujemy, chętnie odpowiemy na pytania.

Przy pytaniach: slajdy zapasowe (przypadki dziekanatu, 7 pełnych sekwencji, 3 diagramy klas,
ekrany) oraz przygotowane odpowiedzi w `PREZENTACJA_OPIS.md`.

---

## Skąd są liczby i nazwy (sprawdzone 27.10.2026)

| Fakt w skrypcie | Źródło |
|---|---|
| kolejny kierunek co 30 min | `frontend/src/pages/AdminRounds.tsx` (domyślny krok 30 min), `IMPLEMENTACJA.md` |
| ok. 1000 osób w szczycie, 20 000 kont | `IMPLEMENTACJA.md`, „Duży ruch” |
| worker: audyt co minutę | `backend/app/worker.py` (`AUDIT_EVERY_S = 60`, pętla co 5 s) |
| 28 przypadków użycia (UC0–UC27) | `diagramy/przypadki_uzycia_*.puml`, `README.md` §4 |
| UC2 dołącza UC3, UC4, UC22; UC5 rozszerza UC2 | `diagramy/przypadki_uzycia_student.puml` |
| krok 4 = blokada studenta, krok 8 = blokada grupy | `diagramy/sekwencja_zapis_skrot.png` |
| krok 5 = blokada B z `NOWAIT`, ramka 55P03 | `diagramy/sekwencja_awans_skrot.png` |
| 409 / 429 / 503, format `{code, message, details}` | `backend/app/errors.py`, `backend/app/traffic.py`, `README.md` §9 |
| przeglądarka sama ponawia (do 4 razy, Retry-After × 1–2) | `frontend/src/api.ts` |
| 7 diagramów sekwencji, 3 diagramy klas z metodami | `diagramy/`, `README.md` §5, §7 |
| `check_student`, `decide_seat` i ich parametry | `backend/app/domain/enrollment_rules.py` |
| 15 tabel | `backend/migrations/versions/0001_initial.sql` |
| 11. zapis na 10 miejsc odrzucony przez `CHECK` | `IMPLEMENTACJA.md`, „Logika biznesowa poza bazą” |
| student_id z tokenu, prowadzący tylko swoje grupy | `backend/app/api/student.py`, `lecturer.py`, `README.md` §8 |
| 35 testów przechodzi | `uv run pytest` na PostgreSQL 16.15 – 35 passed (27.10.2026) |
| p95 zapisu 1,92 s, 0 ponowień; 3 kierunki – 0 przepełnień | `IMPLEMENTACJA.md`, tabela wyników k6 |

## Próba

1. Każda osoba czyta swój fragment na głos ze stoperem: Kamil ≤ 2:15, Bartosz ≤ 2:05,
   Krzysztof ≤ 2:15.
2. Kto przekracza czas, skraca u siebie, np. pomija zdanie o stosie (slajd 2), o pominiętych
   (slajd 5) albo o refaktoryzacji (slajd 8).
3. Jedna próba całości ze zmianami osób i przełączaniem slajdów – cel 6:30–6:45.
4. Na slajdach 4 i 5 wskazywać numery kroków na diagramie – słuchacz idzie za palcem.
