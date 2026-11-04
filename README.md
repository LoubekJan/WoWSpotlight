# WoWSpotlight

WoWSpotlight je PoC pro tvorbu vlastních tanců z videa ve WoW 3.3.5a. Hráč otevře panel příkazem `/spotlight`, vybere MP4 a po zpracování v ComfyUI spustí tanec tlačítkem **Play dance**. Klient načte animaci za běhu. Druhý hráč uvidí stejný pohyb po ručním načtení stejného klipu do svého klienta.

## Spuštění připraveného klienta

1. Spusť [Start Spotlight.cmd](<Start Spotlight.cmd>). Otevře testovací WoW z `C:\WoWModding\SpotlightPoC\LiveActor` a pomocnou aplikaci Windows. Výchozí adresa ComfyUI je `http://127.0.0.1:8188`. Při jiné cestě nebo adrese ji předej spouštěči.

   ```powershell
   & '.\Start Spotlight.cmd' --client-dir 'C:\WoWModding\SpotlightPoC\LiveActor' --comfy-url 'http://127.0.0.1:8188'
   ```

2. Přihlas se za lidskou mužskou postavu, nech WoW v režimu okna a zadej `/spotlight`.
3. Klikni na **Upload video** a vyber MP4 s jedním tanečníkem. Po zobrazení **Your dance is ready** klikni na **Play dance**. Pokud během převodu přepneš do jiné aplikace, stav se zobrazí po návratu do WoW.

Klip najdeš ve složce klienta jako `Spotlight\active.pose.json`. Průběh a chyby pomocné aplikace jsou v `Logs\SpotlightBridge.log`.

## První instalace

- [Příprava testovacího klienta a zkouška s druhým hráčem](tools/dance_capture/live_lab/README.md)
- [Instalace uzlů a workflow v ComfyUI](docs/comfyui.md)
- [Původní extraktor a náhled animace bez realmu](tools/dance_capture/README.md)

Klient WoW, knihovnu StormLib a model MediaPipe je potřeba dodat podle návodů. Zdrojové soubory zahrnují doplněk do WoW, pomocnou aplikaci pro Windows, nástroje pro sestavení klientského balíčku, uzly ComfyUI a workflow.

## Rozsah PoC

Ověřeno na Windows s klientem WoW 3.3.5a enUS build 12340 a kostrou `HumanMale`. ComfyUI zpracuje nejvýše prvních 17,7 sekundy videa a vytvoří rotační stopy pro 20 kostí. Pohyb probíhá na místě. Každý klient používá jeden sdílený slot animace, takže ruční výměna klipu ovlivní tanečníky, kteří v daném klientu používají stejný model a slot.
