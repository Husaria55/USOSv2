# Etap 5 (18.XI) – skrypt prezentacji (ok. 7 minut)

Slajdy: `prezentacja/prezentacja.pdf`: tytuł, 9 slajdów treści, „Dziękujemy”, potem slajdy zapasowe
(pełne diagramy, klasy, ER, ekran dziekanatu, tabela „co może pójść nie tak”).
Czasy w kolumnie „do” są też w komentarzach `% N --- m:ss` w `prezentacja.tex`.

- **Podział:** Kamil – slajdy 0–3 (zadanie, tura preferencyjna, przypadki użycia),
  Bartosz – 4–6 (optymalizator, przydział, model danych), Krzysztof – 7–10 (luki, zmiana terminu, testy).
- Zmiana osoby bez zapowiadania – od razu treść.
- Liczby muszą zostać takie, jak w tekście: każda jest wynikiem testu albo pomiaru (tabela na końcu).

---

## Slajd 0 – Tytuł · Kamil · do 0:10

> Dzień dobry. System zapisów na zajęcia, etap piąty: projekt końcowy.

## Slajd 1 – Zadanie i punkt wyjścia · Kamil · do 0:50

> Dostaliśmy dwa zadania. Pierwsze: zapisy nie w kolejności zgłoszeń, tylko według preferencji.
> Student nadaje przedmiotom wagi, system optymalizuje przydział, a wagi można zmieniać w trakcie
> zapisów. Drugie: testy braku kolizji w planie, także przy zmianie harmonogramu w trakcie zapisów
> i przy przydziale z kolejki. Z otrzymanego projektu mieliśmy tylko slajdy, bez kodu, więc
> rozszerzenie zbudowaliśmy na naszym działającym systemie. Wszystko, co pokażemy, jest
> zaimplementowane i przetestowane: dziewięćdziesiąt sześć testów, z czego sześćdziesiąt jeden nowych.

## Slajd 2 – Tura preferencyjna · Kamil · do 1:45

Wskazywać kroki 1–4, potem zrzut ekranu.

> Tura ma teraz tryb: kolejka albo preferencje. W turze preferencyjnej student dostaje sto punktów
> i rozdziela je między przedmioty, a dla każdego przedmiotu układa akceptowane grupy od najbardziej
> chcianej. Może to zmieniać dowolnie często, aż do zamknięcia tury. Co pięć minut system liczy
> symulację i student widzi, co by dostał i dlaczego czegoś nie – tutaj po prawej. Jeśli nie
> dostałby ważnego przedmiotu, przesuwa na niego punkty. Po zamknięciu tury przydział wykonuje się
> raz i trafia do planów. Wspólna pula punktów sprawia, że waga coś znaczy, bo nie da się dać
> wszystkiemu maksimum. Remisy rozstrzyga losowanie z zapisanym ziarnem, więc każdy wynik da się odtworzyć.

## Slajd 3 – Przypadki użycia · Kamil · do 2:20

> Nowe przypadki użycia: student zgłasza i zmienia preferencje oraz sprawdza przewidywany przydział.
> Worker co pięć minut symuluje przydział, a po zamknięciu tury przydziela miejsca. Dziekanat tworzy
> turę preferencyjną, może uruchomić symulację albo przydział ręcznie i ogląda raport. Przydział
> korzysta z tych samych reguł co zwykły zapis: wymagania wstępne i wykrywanie kolizji.

## Slajd 4 – Optymalizator · Bartosz · do 3:15

> Celem jest maksymalna suma użyteczności. Użyteczność to waga razy współczynnik rangi grupy:
> pierwszy wybór sto procent, drugi dziewięćdziesiąt i tak dalej. Waga decyduje więc, czy student
> dostanie przedmiot, a ranga – którą grupę. Obowiązują te same ograniczenia co przy zapisie:
> limity, brak kolizji, wymagania, jedna grupa danego typu, a wykład z laboratorium wszystko albo nic.
> Przez kolizje problem jest NP-trudny, dlatego stosujemy heurystykę: najpierw zachłannie według wag,
> potem poprawa lokalna – przenosimy kogoś do jego drugiej grupy albo zwalniamy tańszy przydział,
> jeśli suma rośnie. Jakość zmierzyliśmy: na tysiącu losowych instancji porównanie z przeglądem
> zupełnym daje średnio dziewięćdziesiąt dziewięć i osiem dziesiątych procent optimum, a w
> dziewięćdziesięciu siedmiu procentach dokładnie optimum. Kierunek, czyli tysiąc studentów, liczy
> się około siedmiu sekund.

## Slajd 5 – Przydział końcowy (sekwencja) · Bartosz · do 4:00

Pokazywać kroki 3, 4, 8–9, 10.

> Przydział końcowy robi worker, w jednej transakcji. Blokuje turę, studentów i grupy – w tej samej
> kolejności co zwykły zapis, więc nie ma zakleszczeń. Jeśli przydział już był, na przykład zrobiła
> go druga instancja workera, kończy bez zmian. Wynik algorytmu sprawdza niezależna funkcja verify;
> jeśli coś się nie zgadza, nic nie zapisujemy. Unikalny indeks w bazie gwarantuje jeden przydział
> końcowy na turę, a ograniczenie limitu miejsc w bazie zostaje ostatnią siatką bezpieczeństwa.

## Slajd 6 – Model danych · Bartosz · do 4:35

> W bazie przybyło pięć tabel. Preferencje to waga przedmiotu i ranga grupy, powiązane kluczem
> złożonym, więc grupę można wybrać tylko w zgłoszonym przedmiocie. Przebieg przydziału zapisuje
> ziarno i statystyki, a każdy nieprzydzielony przedmiot ma w bazie wymagany powód. Przy grupie
> doszła wersja harmonogramu – o niej za chwilę.

## Slajd 7 – Dwie luki · Krzysztof · do 5:20

> Pisząc testy kolizji, trafiliśmy na dwie luki, które sami wpisaliśmy w etapie trzecim jako znane
> ograniczenia. Dziekanat mógł przenieść termin grupy bez sprawdzania planów zapisanych studentów.
> A zapis brał terminy z pamięci podręcznej procesu, więc przez dziesięć sekund inny proces mógł
> przepuścić kolizję. Teraz zmiana terminu blokuje grupę i jej studentów i jest odrzucana, jeśli
> u kogokolwiek powstałaby kolizja. Każda zmiana podnosi wersję harmonogramu, a zapis i awans
> z kolejki porównują ją pod blokadą grupy. Do audytu doszło wykrywanie kolizji, napisane w SQL
> niezależnie od kodu, który decyduje o zapisie.

## Slajd 8 – Zmiana terminu vs zapis (sekwencja) · Krzysztof · do 5:55

> Tu oba przypadki naraz. Jeśli pierwszy jest dziekanat, zapis ze starym terminem w pamięci widzi
> pod blokadą nowszą wersję, wczytuje aktualne terminy i odmawia. Jeśli pierwszy jest student,
> dziekanat widzi go wśród zapisanych i dostaje odmowę z jego numerem indeksu.

## Slajd 9 – Testy · Krzysztof · do 6:45

> Każdy test ma trzy części: przygotowanie, wywołanie metod z konkretnymi parametrami i weryfikację.
> Tu przykład: student ma stary termin w pamięci podręcznej, dziekanat przenosi grupę, zapis musi
> wykryć kolizję. Mamy dwadzieścia trzy testy kolizji, siedemnaście tury preferencyjnej
> i dwadzieścia jeden samego optymalizatora. Wyścigi powtarzamy po kilka razy. Sprawdziliśmy też,
> że testy naprawdę działają: po wyłączeniu porównania wersji cztery z nich padają. Wszystkie
> scenariusze z wywołaniami są w pliku TESTY.

## Slajd 10 – Dziękujemy · Krzysztof · do 7:00

> Dziękujemy. Chętnie odpowiemy na pytania.

---

## Przygotowanie do pytań

| Pytanie | Odpowiedź (slajd zapasowy) |
|---|---|
| Dlaczego nie solver ILP? | Optimum tylko dla małych tur, ciężka zależność binarna, nieprzewidywalny czas dla tysięcy studentów. Mamy sformułowanie ILP w README §8 i zmierzoną jakość heurystyki względem optimum. |
| Czy student może oszukać system wagami? | Pula jest wspólna i stała, więc więcej punktów na jeden przedmiot oznacza mniej na inne. Symulacja pokazuje tylko jego wynik, nie cudze wagi. |
| Co jeśli dwóch studentów ma tę samą wagę? | Los z ziarnem; jeden los na studenta na cały przebieg, ziarno w `allocation_run` – wynik da się odtworzyć (test P11, A2). |
| Co jeśli tura zamyka się w trakcie zapisu preferencji? | `FOR SHARE` na turze: zgłoszenie albo wchodzi do przydziału, albo `ROUND_CLOSED` (test P5). Zapasowy slajd „co może pójść nie tak”. |
| Co jeśli worker padnie w trakcie przydziału? | Transakcja się wycofuje, tura nadal „bez FINAL”, następny przebieg robi przydział od nowa. Dwa workery: `UNIQUE` na FINAL. |
| Co z nieprzydzielonymi? | Dostają powiadomienie z powodem; po turze preferencyjnej dziekanat planuje turę kolejkową (uzupełniającą). Ograniczenie opisane w README §12. |
| Skąd wiadomo, że brak kolizji? | Każdy test kończy się audytem z niezależną implementacją kolizji w SQL; test K17 pokazuje, że audyt wykrywa wstrzykniętą kolizję. |
| Dlaczego nie przejęliście architektury z otrzymanego projektu? | Był tylko w slajdach; nasza architektura rozwiązuje te same problemy bez Redis/Celery (outbox, worker na bazie). Przejęliśmy jawne „co jeśli” w przypadkach użycia i dziennik operacji systemowych (README §1.3). |

## Źródła liczb

| Liczba | Skąd |
|---|---|
| 96 testów (61 nowych: 23 + 17 + 21) | `uv run python -m pytest --collect-only -q` |
| 99,8% / 97,1% / 80% (heurystyka), 98,1% / 83,9% / 55% (zachłanny) | 1000 instancji `random_instance` vs `exact_optimum` z `tests/test_allocation_domain.py` |
| ok. 7 s dla 1000 studentów × 6 przedmiotów | instancja z testu A11 (`test_scale_one_program_round_is_fast`), pomiar na maszynie deweloperskiej |
| K13–K16 padają po wyłączeniu wersji | ręczna mutacja `_current_target` (zawsze zwraca cache) |
| 100 pkt, symulacja co 5 min | `DEFAULT_POINTS_BUDGET`, `allocation_preview_interval_s = 300` |
