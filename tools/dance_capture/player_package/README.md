# WoWSpotlight pro dalšího hráče

Rozbal celý `WoWSpotlight-Player.zip` do jedné složky. Připrav si oddělený čistý klient **WoW 3.3.5a enUS, build 12340**. Pro každou roli použij vlastní kopii klienta.

1. Pro tvorbu nebo sledování tanců nainstaluj přiložený `dependencies\python-3.12.10-amd64.exe`. Pokud už máš 64bitový Python 3.12 s Python Launcherem a Tcl/Tk, pokračuj rovnou. Pro offline náhled stačí samotný WoW.
2. Pro tvorbu nebo sledování tanců na AI World Lab nastav v klientu soubor `Data\enUS\realmlist.wtf` na `set realmlist 192.168.0.248`. Přihlaš se vlastním účtem na stejný testovací realm jako ostatní. ComfyUI i služba pro sdílení jsou dostupné v síti AI World Lab.
3. Vypni WoW a otevři **Spotlight.cmd**. Napiš `Creator`, `Viewer` nebo `Preview` a vlož cestu ke složce, ve které je `WoW.exe`. Spouštěč z balíčku zkopíruje potřebný patch a doplněk a otevře klienta. Pro další spuštění použij stejný spouštěč.

## Režimy

| Volba | Co udělat ve WoW | Instalovaný patch |
| --- | --- | --- |
| `Creator` | Přihlas se za lidskou mužskou postavu v režimu okna. Zadej `/spotlight`, klikni na **Upload video** a po dokončení na **Play dance**. | `Data\enUS\patch-enUS-Z.MPQ` |
| `Viewer` | Přihlas se a zůstaň na výběru postavy. Stiskni Enter v okně spouštěče. Po **Spotlight viewer is ready** vstup do světa a nech okno spouštěče otevřené. | `Data\patch-Z.MPQ` |
| `Preview` | Dvě ukázkové animace uvidíš na přihlašovací obrazovce. | `Data\patch-Z.MPQ` |

## Sdílení vlastního tance

Pro tvorbu a přehrání na vlastním klientu stačí režim `Creator`. Pro přenos k divákovi ti správce Spotlightu předá token k tvé postavě. Ulož jej jako `moje-postava.token` do rozbalené složky vedle `Spotlight.cmd`. V PowerShellu otevřeném ve stejné složce spusť následující příkaz se skutečnou cestou ke klientu.

```powershell
& '.\Spotlight.cmd' -Role Creator -ClientDir 'C:\WoW\Creator' -RelayTokenFile '.\moje-postava.token'
```

Divák se stejným realmem načte sdílený tanec, jakmile má tanečníka na dohled. Průběh tvorby se zapisuje do `Logs\SpotlightBridge.log` ve složce klienta.
