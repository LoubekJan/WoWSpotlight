# WoWSpotlight

WoWSpotlight je PoC pro tvorbu vlastních tanců z videa ve WoW 3.3.5a. Hráč otevře panel příkazem `/spotlight`, vybere MP4 a po zpracování v ComfyUI najde klip v knihovně **My dances**. Klient načte animaci za běhu a připravený klient diváka si ji může [automaticky stáhnout](docs/sharing.md).

## Spuštění připraveného klienta

1. Na AI World Lab spusť `C:\WoWModding\SpotlightPoC\Start Spotlight.cmd`. Otevře testovací WoW z `C:\WoWModding\SpotlightPoC\LiveActor` a pomocnou aplikaci Windows. Pro vlastní instalaci použij [spouštěč z repozitáře](<Start Spotlight.cmd>), který má výchozí adresu ComfyUI `http://127.0.0.1:8188`.

   ```powershell
   & '.\Start Spotlight.cmd' --client-dir 'C:\WoWModding\SpotlightPoC\LiveActor' --comfy-url 'http://127.0.0.1:8188'
   ```

2. Přihlas se za lidskou mužskou postavu a nech WoW v režimu okna. Pokud bylo WoW při aktualizaci doplňku otevřené, zadej `/reload`. Pak otevři `/spotlight`.

## Moje tance

1. Klikni na **Upload video** a vyber MP4 s jedním tanečníkem. Hotový klip se uloží do **My dances**. Po neúspěšném převodu tlačítko **Retry conversion** zopakuje převod stejného videa v aktuální relaci pomocné aplikace. Pokud během převodu přepneš do jiné aplikace, stav se zobrazí po návratu do WoW.
2. Kliknutím na uložený tanec jej načti. Pro přejmenování uprav pole **Selected dance name** a klikni na **Rename**. Po zobrazení **Your dance is ready** klikni na **Play dance**.

Knihovna je ve složce klienta pod `Spotlight\library` a ukládá se zvlášť pro každou postavu podle jejího GUID. Po dalším přihlášení stačí vybrat uložený tanec. Knihovna se plní převody z této verze. Pro starší klip v `Spotlight\active.pose.json` použij [ruční postup](tools/dance_capture/live_lab/README.md#ruční-ověření-s-divákem). Průběh a chyby pomocné aplikace jsou v `Logs\SpotlightBridge.log`.

## První instalace

- [Příprava testovacího klienta a zkouška s druhým hráčem](tools/dance_capture/live_lab/README.md)
- [Instalace uzlů a workflow v ComfyUI](docs/comfyui.md)
- [Původní extraktor a náhled animace bez realmu](tools/dance_capture/README.md)
- [Duet na testovacím realmu a samostatný náhled](docs/duet.md)
- [Automatické sdílení a přehrávání u diváka](docs/sharing.md)

Klient WoW, knihovnu StormLib a model MediaPipe je potřeba dodat podle návodů. Zdrojové soubory zahrnují doplněk do WoW, pomocnou aplikaci pro Windows, nástroje pro sestavení klientského balíčku, uzly ComfyUI a workflow.

## Rozsah PoC

Ověřeno na Windows s klientem WoW 3.3.5a enUS build 12340 a kostrou `HumanMale`. ComfyUI zpracuje nejvýše prvních 17,7 sekundy videa a vytvoří rotační stopy pro 20 kostí. Pohyb probíhá na místě. Automatické sdílení podporuje dva tanečníky současně v připraveném klientu diváka.
