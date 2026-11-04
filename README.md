# WoWSpotlight

WoWSpotlight je PoC pro tvorbu vlastních tanců z videa ve WoW 3.3.5a. Hráč otevře panel příkazem `/spotlight`, vybere MP4 a po zpracování v ComfyUI najde klip v knihovně **My dances**. Klient načte animaci za běhu a připravený klient diváka si ji může [automaticky stáhnout](docs/sharing.md).

## Spuštění v čistém klientu

Zkopíruj obsah `C:\WoWSpotlight\artifacts\player-files` do čistého klienta WoW 3.3.5a enUS a spusť jeho `WoW.exe`. Přihlas se za lidskou mužskou postavu, nech WoW v režimu okna a otevři `/spotlight`. Stejný klient automaticky přehrává sdílené tance ostatních. [Přesný postup pro lab](docs/player-files.md)

## Moje tance

1. Klikni na **Upload video** a vyber MP4 s jedním tanečníkem. Hotový klip se uloží do **My dances**. Po neúspěšném převodu tlačítko **Retry conversion** zopakuje převod stejného videa v aktuální relaci pomocné aplikace. Pokud během převodu přepneš do jiné aplikace, stav se zobrazí po návratu do WoW.
2. Kliknutím na uložený tanec jej načti. Pro přejmenování uprav pole **Selected dance name** a klikni na **Rename**. Po zobrazení **Your dance is ready** klikni na **Play dance**.

Knihovna je ve složce klienta pod `Spotlight\library` a ukládá se zvlášť pro každou postavu podle jejího GUID. Po dalším přihlášení stačí vybrat uložený tanec. Knihovna se plní převody z této verze. Pro starší klip v `Spotlight\active.pose.json` použij [ruční postup](tools/dance_capture/live_lab/README.md#ruční-ověření-s-divákem). Průběh a chyby pomocné aplikace jsou v `Logs\SpotlightBridge.log`.

## První instalace

Složka `artifacts` obsahuje místní výstupy sestavené z dat klienta. Návody níže zahrnují i starší samostatné testy jednotlivých částí.

- [Sestavení souborů pro společný klient](docs/player-files.md#sestavení-souborů-pro-lab)
- [Starší zkouška s odděleným klientem diváka](tools/dance_capture/live_lab/README.md)
- [Instalace uzlů a workflow v ComfyUI](docs/comfyui.md)
- [Původní extraktor a náhled animace bez realmu](tools/dance_capture/README.md)
- [Duet na testovacím realmu a samostatný náhled](docs/duet.md)
- [Automatické sdílení a přehrávání u diváka](docs/sharing.md)

Pro sestavení klientských souborů potřebuješ data WoW a knihovnu StormLib. Model MediaPipe patří na server s ComfyUI. Zdrojové soubory zahrnují doplněk do WoW, pomocnou aplikaci pro Windows, nástroje pro sestavení klientských souborů, uzly ComfyUI a workflow.

## Rozsah PoC

Ověřeno na Windows s klientem WoW 3.3.5a enUS build 12340 a kostrou `HumanMale`. ComfyUI zpracuje nejvýše prvních 17,7 sekundy videa a vytvoří rotační stopy pro 20 kostí. Pohyb probíhá na místě. Automatické sdílení podporuje dva tanečníky současně v připraveném klientu diváka.
