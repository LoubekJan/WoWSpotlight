# Jeden klient WoWSpotlight

Na AI World Lab jsou hotové soubory v `C:\WoWSpotlight\artifacts\player-files`. Stejný klient WoW umí vytvářet vlastní tance i přehrávat tance ostatních.

Spotlight přijímá původní podepsaný `WoW.exe` pro enUS build 12340 a ověřené varianty stejného buildu. Před připojením kontroluje také animační data a instrukce klienta, které používá.

1. Vypni čistou kopii WoW **3.3.5a enUS build 12340**. Zkopíruj celý **obsah** složky `player-files` tam, kde je `WoW.exe`. Pro připojení k AI World Labu použij v herním `Data\enUS\realmlist.wtf` řádek `set realmlist 192.168.0.248`.
2. Spusť `WoW.exe`, přihlas se za libovolnou z deseti hratelných ras a použij režim okna. Zadej `/spotlight`, vyber **Upload video** a po zpracování použij **Play dance**. Sdílené tance postav v dosahu na stejném realmu se načítají automaticky.

Vlastní tanec spustíš tlačítkem **Play dance**. Příkaz `/dance` přehraje běžný tanec WoW i po načtení vlastního klipu. Každý klient má prostor pro vlastní tanec a dva současně sledované tanečníky.

Při přechodu ze starší verze použij celý nový balíček včetně `Data\patch-Z.MPQ`. Pro přehrání použij základní podobu postavy. Divák použije kostru tanečníka, takže klip správně přiřadí i postavě jiné rasy nebo pohlaví.

Pro stažení hotového tance otevři `/spotlight` → **Gallery** a klikni na řádek s **Download**. Přepni na **My dances**, vyber stažený tanec a po načtení stiskni **Play dance**. Webovou galerii otevřeš na síti AI World Labu. [Galerie Spotlight](http://192.168.0.248:9093/)

Složka klienta po zkopírování obsahuje tyto nové soubory a adresáře.

```text
WoW.exe
dinput8.dll
SpotlightDuet.lab
Data\patch-Z.MPQ
Interface\AddOns\SpotlightDanceLab\
Spotlight\
```

`Spotlight` obsahuje přibalený Python a potřebné knihovny. `dinput8.dll` při spuštění hry předá požadavky DirectInput systémové knihovně a na pozadí spustí Spotlight. Stav pomocné části se zapisuje do `Logs\SpotlightBridge.log` v klientu.

Na AI World Labu se klient pro **sdílení vlastního tance** automaticky ověří přes právě přihlášenou postavu. Oba hráči mohou použít stejný balíček. Volba `--no-relay-realm-auth` při sestavení zachová původní ruční nastavení pro lab se samostatnými tokeny. [Nastavení sdílecí služby](sharing.md#nastavení-služby-spotlight)

## Adresy služeb

Při startu Spotlight použije hostitele z `set realmlist` v `Data\enUS\realmlist.wtf`. ComfyUI použije port `8188`, galerie `9093` a relay `8765`. Případný přihlašovací port WoW v `realmlist.wtf` patří jen ke hře.

V `Spotlight\settings.json` můžeš pro jednotlivé služby výslovně zadat `comfy_url`, `gallery_url` nebo `relay_url`. Každá vyplněná URL má přednost. Po úpravě nastavení restartuj WoW. Při použití ručního `relay.token` uveď výslovně i `relay_url`.

## Sestavení souborů pro lab

Z kořene projektu sestav `dinput8.dll` pomocí MSVC s nástroji pro C++ a potom připrav novou složku souborů. Pro sestavení použij 64bitový Python 3.12 pro Windows s Tcl/Tk, StormLib v `tools\dance_capture\vendor` a data ověřeného klienta.

```powershell
& '.\tools\dance_capture\bootstrap\build.cmd' '.\artifacts\unified-work\dinput8.dll'
py -3.12 -B '.\tools\dance_capture\build_unified_files.py' '.\artifacts\player-files' `
    --client-data 'C:\WoWModding\Client-Lab\Data' --bootstrap '.\artifacts\unified-work\dinput8.dll'
```

Výstupní složka musí být nová. Volba `--realmlist` přidá soubor s adresou zvoleného realmu. Pro výslovné adresy služeb použij `--comfy-url`, `--relay-url` nebo `--gallery-url`.
