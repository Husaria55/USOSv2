# Etap 5 (18.XI) – skrypt prezentacji (ok. 8 minut)

Slajdy: `prezentacja/prezentacja.pdf` – tytuł, plan, 13 slajdów treści, „Dziękujemy”, slajdy zapasowe
(UC1b, UC7, przypadki użycia administratora, algorytm, klasy, tabele metod, API, „co może pójść nie tak”).
Numery slajdów jak w PDF (0 = tytuł, 1 = plan). Jeśli limit to 7 minut, można pominąć slajd 5
(komponenty) i 8 (przypadki użycia) – są w README.

**Oś opowieści:** dostaliśmy projekt → przeszliśmy po ich diagramach z nowymi wymaganiami → znaleźliśmy,
gdzie mogą powstać kolizje → zmieniliśmy ich schematy (przed / po) → dobudowaliśmy preferencje na ich
infrastrukturze → testy to potwierdzają.

**Podział:** Kamil – slajdy 0–4, Bartosz – 5–9, Krzysztof – 10–14.

---

## Slajd 0–1 – Tytuł, plan · Kamil · do 0:15
> Dzień dobry. Przedstawiamy etap piąty: rozwinięcie projektu systemu zapisów, który dostaliśmy od innej grupy.

## Slajd 2 – Punkt wyjścia · Kamil · do 0:45
> Dostaliśmy projekt z React, FastAPI, logowaniem przez SSO, PostgreSQL, Redisem i Celery do awansu
> z listy oczekujących. Był spójny, więc zostawiliśmy architekturę, nazwy klas i format dokumentacji.
> Nowe wymagania to testy braku kolizji – także przy zmianie harmonogramu i awansie z kolejki – oraz
> zapisy według preferencji. Zaczęliśmy od tego, że przeszliśmy po każdym ich diagramie sekwencji
> i szukaliśmy sytuacji, w których student dostaje kolidujące zajęcia.

## Slajd 3 – Analiza · Kamil · do 1:45
> Znaleźliśmy cztery takie miejsca. Pierwsze: przy zapisie reguły są sprawdzane przed transakcją,
> a blokowana jest tylko sekcja. Student, który w dwóch kartach zapisuje się naraz na dwie sekcje
> o tej samej porze, dostaje obie. Drugie: awans z kolejki nie blokuje kandydata, więc ten może
> w tej samej chwili zapisać się gdzie indziej. Trzecie: zmiana terminu sekcji sprawdza tylko salę, nie
> plany zapisanych. Czwarte: zapis czyta terminy sekcji bez jej blokady. Do tego doprecyzowaliśmy,
> że styk zajęć nie jest kolizją, i dodaliśmy zapytanie kontrolne do testów.

## Slajd 4 – Architektura przed / po · Kamil · do 2:15
> W architekturze zmiany są małe. Dochodzi Celery Beat – harmonogram zadań, który jest częścią Celery
> już obecnego w projekcie. Serwery aplikacji dostają dwa serwisy, workery – zadania przydziału, a baza – nowe tabele.

## Slajd 5 – Komponenty przed / po · Bartosz · do 2:45
> Na poziomie komponentów: zielone są nowe – serwis preferencji, serwis przydziału i sam algorytm jako
> osobna klasa bez bazy. Żółte są zmienione: zapis, kolejka i katalog dostały blokady i sprawdzanie
> planów, a silnik reguł – metodę sprawdzającą plany zapisanych przy zmianie terminu.

## Slajd 6 – UC1a przed / po · Bartosz · do 3:25
> Tak wygląda zmiana w ich diagramie zapisu. Zielone kroki są nowe: transakcja zaczyna się od blokady
> studenta, potem blokujemy sekcję i dopiero wtedy sprawdzamy reguły. Dwa zapisy tego samego studenta
> idą więc po kolei, a zmiana terminu sekcji nie może się wcisnąć między sprawdzenie a zapis.

## Slajd 7 – UC2 przed / po · Bartosz · do 3:50
> W awansie z kolejki blokujemy kandydata. Tu kolejność blokad jest odwrotna, więc bez czekania – jeśli
> kandydat jest akurat zajęty, transakcja się wycofuje i zadanie wraca do kolejki. Mechanizm ponawiania
> był już w ich projekcie.

## Slajd 8 – Przypadki użycia · Bartosz · do 4:15
> Do ich przypadków użycia dodaliśmy siedem nowych. Student zgłasza preferencje i ogląda przewidywany
> przydział, zegar uruchamia symulację i przydział, a administrator ustawia tryb zapisów, zmienia
> harmonogram w trakcie zapisów i ogląda raport.

## Slajd 9 – Tura preferencji · Bartosz · do 5:00
> Sam proces: dziekanat ustawia semestr w trybie preferencji z pulą stu punktów. Student rozdziela punkty
> między przedmioty i układa sekcje w kolejności, a zmieniać to może do końca okna. Co pięć minut
> system liczy symulację, więc student widzi, czego by nie dostał, i może przesunąć punkty. Po końcu
> okna przydział wykonuje się raz. Wspólna pula sprawia, że waga coś znaczy, a remisy rozstrzyga
> losowanie z zapisanym ziarnem, więc wynik da się odtworzyć.

## Slajd 10 – Model danych przed / po · Krzysztof · do 5:35
> W bazie semestr dostał tryb i pulę, zapis – źródło. Doszły cztery tabele: wagi kursów, kolejność
> sekcji, przebiegi przydziału i wyniki. Unikalny indeks pozwala na jeden przydział końcowy na semestr,
> a każdy nieprzydzielony kurs musi mieć zapisany powód.

## Slajd 11 – UC9 · Krzysztof · do 6:05
> Przydział końcowy uruchamia Celery Beat. Worker blokuje semestr, studentów i sekcje – w tej samej
> kolejności co zapis – liczy przydział i sprawdza go niezależnie. Jeśli coś się nie zgadza, nic nie
> zapisuje. Gdy worker padnie, transakcja się wycofuje, a przydział wykona się ponownie.

## Slajd 12 – Algorytm · Krzysztof · do 6:50
> Celem jest maksymalna suma wag, z karą za dalsze sekcje na liście. Kolizje czynią problem NP-trudnym,
> więc mamy heurystykę: zachłannie według wag, potem poprawa lokalna, która przenosi ludzi między ich
> akceptowanymi sekcjami. Zrobiliśmy prototyp i porównaliśmy go z przeglądem zupełnym na tysiącu
> instancji: średnio dziewięćdziesiąt dziewięć i dziewięć dziesiątych procent optimum. Tysiąc studentów
> liczy się w trzy sekundy.

## Slajd 13 – UC11 · Krzysztof · do 7:20
> Zmiana harmonogramu w trakcie zapisów: system blokuje sekcję i jej studentów, sprawdza ich plany
> i odrzuca zmianę, jeśli komuś powstałaby kolizja – z listą tych osób. Na dole widać, że w żadnej
> kolejności z równoległym zapisem kolizja nie powstaje.

## Slajd 14 – Testy · Krzysztof · do 8:10
> Każdy test ma trzy części: przygotowanie, wywołanie metod z konkretnymi parametrami i weryfikację.
> Ten przykład to dwa równoległe zapisy tego samego studenta. Na otrzymanym projekcie nie
> przechodzi, po naszej zmianie przechodzi. Mamy czternaście scenariuszy kolizji, dwanaście dla
> preferencji i osiem testów algorytmu, które są zaimplementowane i przechodzą. Po każdym teście
> zapytanie kontrolne sprawdza, czy w bazie nie ma kolizji. Dziękujemy.

---

## Przygotowanie do pytań

| Pytanie | Odpowiedź |
|---|---|
| Dlaczego zmienialiście ich zapis, skoro działał? | Działał dla jednego żądania; przy dwóch równoległych żądaniach tego samego studenta powstawała kolizja (test K8 nie przechodzi na ich wersji). |
| Dlaczego `NOWAIT` w awansie? | Tam blokujemy sekcję, potem studenta – odwrotnie niż przy zapisie. Czekanie mogłoby dać zakleszczenie; `NOWAIT` daje szybki błąd i ponowienie zadania Celery. |
| Dlaczego nie solver ILP? | Ciężka zależność, nieprzewidywalny czas dla tysięcy studentów; heurystyka ma zmierzone 99,9% optimum (README §8). |
| Czy można oszukać wagami? | Pula jest wspólna – więcej punktów na jeden kurs to mniej na inne. Symulacja pokazuje tylko własny wynik. |
| Co z nieprzydzielonymi? | Dostają powód; po turze preferencji dziekanat może otworzyć zapisy uzupełniające (FCFS) z listami oczekujących. |
| Co jeśli worker padnie? | `ROLLBACK`, semestr dalej bez przydziału końcowego, Celery ponawia; unikalny indeks wyklucza podwójny przydział. |
| Skąd wiadomo, że testy coś sprawdzają? | Wyrocznia SQL niezależna od silnika reguł; K14 pokazuje, że wykrywa wstrzykniętą kolizję. |
