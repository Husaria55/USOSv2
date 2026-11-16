 Przed chwilą wysłałem Wam projekty do drugiej części etapu. Jako odpowiedź na wiadomości z przesłanymi do mnie wcześniej projektami. Jeśli ktoś nie otrzymał to proszę o kontakt przez Teams.

Druga część projektu obejmuje dwa oddzielne zadania: testy i rozbudowę funkcjonalności.

W ramach opracowanych testów, należy opracować scenariusze testowe i przedstawić je w formie algorytmów, lub też prostej implementacji. W każdym przypadku, również przy przedstawianiu w formie algorytmu należy wołać konkretne metody testowanego oprogramowania z konkretnymi parametrami i sprawdzać zwracane rezultaty. Typowy test będzie składał sie zatem z 3 części:
1) przygotowania - ustawienia systemu w odpowiednim stanie
2) właściwego testu - wołania odpowiednich metod w ramach scenariusza testowego
3) weryfikacji rezultatu.

Rozbudowa funkcjonalności to dodanie odpowiedniego rozszerzenia struktury danych (jeśli wymagane) i odpowiednich klas/metod które zapewnią realizację wskazanej funkcjonalności.

W zależności od przydzielonego Waszej grupie tematu/projektu, zakres prac jest następujący:

Temat - Przesyłki kurierskie

Testy: weryfikacja procesu nadania/dostarczenia przesyłki, z uwzględnieniem możliwości anulowania przesyłki na etapie zamówienia, nadania, odmowy odbioru przez kuriera, zgubienia przez kuriera, odmowy odbioru przez klienta itp.

Nowa funkcjonalność: obsługa zwrotów (w tym częściowych - jeden z kilku zamówionych produktów)

Temat - Mini Bank

Testy: poprawność realizacji przelewu zwykłego i walutowego, z weryfikacją zmiany stanu kont, zachowania balansu (konta sumują się do zera), ledgera itp.

Nowa funkcjonalność: obsługa przelewów międzybankowych przez zewnętrzny asynchroniczny system clearingowy (jak polski elixir)

Temat - Zapisy na zajęcia

Testy: weryfikacja braku kolizji zajęć dla studenta w różnych scenariuszach zapisu do grup i zmiany harmonogramu w trakcie zapisów, szczególnie w kontekście przydzielania zajęć z kolejki

Nowa funkcjonalność: zapisy oparte nie na kolejce (kto pierwszy ten lepszy), ale na systemie preferencji - student może zdefiniować które przedmioty są dla niego 'najcenniejsze' (przypisać wagi) a system optymalizuje przydział zajęć tak aby uzyskać jak najlepsze dopasowanie. Student może modyfikować swoje wagi (preferencje) w trakcie zapisów