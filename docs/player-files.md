# Soubory pro ruční přípravu klienta

Na AI World Lab jsou hotové soubory v `C:\WoWSpotlight\artifacts\player-files`. Použij WoW 3.3.5a enUS build 12340. Kopíruj při vypnuté hře do složky, ve které je `WoW.exe`.

## Tvorba tance přes `/spotlight`

Ze složky `Creator` zkopíruj do klienta `Data` a `Interface`. Výsledkem mají být tyto cesty od `WoW.exe`.

```text
Data\enUS\patch-enUS-Z.MPQ
Interface\AddOns\SpotlightDanceLab\SpotlightDanceLab.toc
Interface\AddOns\SpotlightDanceLab\SpotlightDanceLab.lua
```

Soubor `.toc` říká WoW, aby načetl `.lua`, který obsahuje panel Spotlight. MPQ přesměruje herní `/dance` na animační slot Spotlightu.

Pro výběr videa, komunikaci s ComfyUI a načtení pohybu potřebuješ celou složku `Companion`. Ulož ji vedle hry nebo jinam na disk. Obsahuje i `vendor\StormLib.dll`. Na Windows použij 64bitový Python 3.12 s Python Launcherem a Tcl/Tk.

Přihlas se ve WoW za lidskou mužskou postavu a nech klienta v režimu okna. V PowerShellu spuštěném ve složce `player-files` zadej následující příkaz. Cestu `C:\Hry\WoW` nahraď složkou svého `WoW.exe`.

```powershell
py -3.12 -B '.\Companion\spotlight_bridge.py' --client-dir 'C:\Hry\WoW' --comfy-url 'http://192.168.0.248:8188'
```

Nech PowerShell otevřený a ve hře zadej `/spotlight`. Použij **Upload video** a po zpracování **Play dance**. Pro přenos k dalším hráčům použij také adresu služby a token přidělený konkrétní postavě. [Nastavení sdílení pro tanečníka](sharing.md#tanečník)

## Sledování sdílených tanců

Do samostatné kopie klienta zkopíruj obsah `Viewer`. Výsledkem mají být `Data\patch-Z.MPQ`, `SpotlightDuet.lab` vedle `WoW.exe` a složka `Interface\AddOns\SpotlightViewer` s oběma soubory doplňku.

Přihlas se na stejný testovací realm jako tanečník a zůstaň na výběru postavy. V PowerShellu spuštěném ve složce `player-files` vlož tento blok s vlastní cestou ke klientu diváka.

```powershell
$client = 'C:\Hry\WoW-Divak'
$wow = @(Get-Process WoW | Where-Object Path -eq (Join-Path $client 'WoW.exe'))
if ($wow.Count -ne 1) { throw 'Spusť jednu kopii WoW ze složky diváka.' }
py -3.12 -B '.\Companion\spotlight_viewer.py' $wow[0].Id --client-dir $client --relay-url 'http://192.168.0.248:8765'
```

Po hlášce **Spotlight viewer is ready** vstup do světa a nech PowerShell otevřený. Divák si sdílený pohyb stáhne, jakmile má tanečníka na dohled.
