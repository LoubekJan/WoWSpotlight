# Jeden klient WoWSpotlight

Na AI World Lab jsou hotové soubory v `C:\WoWSpotlight\artifacts\player-files`. Stejný klient WoW umí vytvářet vlastní tance i přehrávat tance ostatních.

1. Vypni čistou kopii WoW **3.3.5a enUS build 12340**. Zkopíruj celý **obsah** složky `player-files` tam, kde je `WoW.exe`. `Data\enUS\realmlist.wtf` nastaví připojení k AI World Lab.
2. Spusť `WoW.exe`, přihlas se za lidskou mužskou postavu a použij režim okna. Zadej `/spotlight`, vyber **Upload video** a po zpracování použij **Play dance**. Sdílené tance postav v dosahu na stejném realmu se načítají automaticky.

Složka klienta po zkopírování obsahuje tyto nové soubory a adresáře.

```text
WoW.exe
dinput8.dll
SpotlightDuet.lab
Data\patch-Z.MPQ
Data\enUS\realmlist.wtf
Interface\AddOns\SpotlightDanceLab\
Spotlight\
```

`Spotlight` obsahuje přibalený Python a potřebné knihovny. `dinput8.dll` při spuštění hry předá požadavky DirectInput systémové knihovně a na pozadí spustí Spotlight. Stav pomocné části se zapisuje do `Logs\SpotlightBridge.log` v klientu.

Pro **sdílení vlastního tance** správce přiřadí token k GUID dané postavy a před předáním jej přidá do `Spotlight\relay.token` v souborech pro konkrétního hráče. Hráč může vytvářet vlastní tance pro sebe i sledovat ostatní už se základní sadou souborů. [Nastavení sdílecí služby](sharing.md#nastavení-služby-spotlight)

## Sestavení souborů pro lab

Z kořene projektu sestav `dinput8.dll` pomocí MSVC s nástroji pro C++ a potom připrav novou složku souborů. Pro sestavení použij 64bitový Python 3.12 pro Windows s Tcl/Tk, StormLib v `tools\dance_capture\vendor` a data ověřeného klienta.

```powershell
& '.\tools\dance_capture\bootstrap\build.cmd' '.\artifacts\unified-work\dinput8.dll'
py -3.12 -B '.\tools\dance_capture\build_unified_files.py' '.\artifacts\player-files' `
    --client-data 'C:\WoWModding\Client-Lab\Data' --bootstrap '.\artifacts\unified-work\dinput8.dll'
```

Výstupní složka musí být nová. Pro jiný lab nastav adresu realmu volbou `--realmlist` a adresy služeb volbami `--comfy-url` a `--relay-url`.
