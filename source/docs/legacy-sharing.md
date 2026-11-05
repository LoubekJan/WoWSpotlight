# Historický test sdílení s oddělenými klienty

Tento postup popisuje starší PoC. Pro běžné použití verze 1.0 použij [současný klientský návod](player-files.md) a [serverové nasazení](../../server/README.md#relay). Příklady níže používají vlastní izolované kopie hry v `C:\SpotlightTests`. Nahraď cesty a adresy podle svého prostředí.

## Tanečník

1. Použij připravený klient s doplňkem `SpotlightDanceLab` a mapováním `/dance` z [přípravy historického klienta](../tools/dance_capture/live_lab/README.md).
2. Správce služby musí pro herní GUID této postavy nastavit token. Ulož jej jako jeden řádek do souboru, například `C:\SpotlightTests\moje-postava.token`. Každá postava má vlastní token.
3. Spusť následující příkaz v PowerShellu z kořene repozitáře. Pro druhého tanečníka zadej jeho vlastní `--client-dir` a token.

   ```powershell
   & '.\source\Start Spotlight.cmd' `
       --client-dir 'C:\SpotlightTests\LiveActor' `
       --comfy-url 'http://192.168.0.248:8188' `
       --relay-url 'http://192.168.0.248:8765' `
       --relay-token-file 'C:\SpotlightTests\moje-postava.token'
   ```

4. Ve WoW v režimu okna otevři `/spotlight`, nahraj MP4 a po **Your dance is ready** klikni na **Play dance**. Pohybem postavy ukončíš sdílení. Před načtením dalšího klipu ukonči aktuální tanec.

Pro technickou zkoušku s hotovým souborem lze místo panelu spustit `spotlight_publish.py`. Předej PID již přihlášeného tanečníka, cestu k `*.motion.json`, `--client-dir`, `--relay-url` a `--relay-token-file`. Po hlášce **Ready for /dance** použij běžný `/dance`.

## Divák

1. Spusť `C:\SpotlightTests\Duet\Observer\WoW.exe` a nech ho na **výběru postavy**.
2. V PowerShellu v kořeni repozitáře spusť následující blok. Jakmile vypíše **Spotlight viewer is ready**, vstup do světa. Okno PowerShellu nech otevřené.

   ```powershell
   $dir = 'C:\SpotlightTests\Duet\Observer'
   $wow = @(Get-Process WoW -ErrorAction SilentlyContinue |
       Where-Object Path -eq (Join-Path $dir 'WoW.exe'))
   if ($wow.Count -ne 1) { throw "Spusť právě jedno WoW z $dir." }
   py -3.12 -B .\source\tools\dance_capture\spotlight_viewer.py $wow[0].Id `
       --client-dir $dir --relay-url 'http://192.168.0.248:8765'
   ```

3. Přijď k tanečníkům. Klient stáhne potřebné klipy sám. Stažené soubory najdeš pod `Observer\Spotlight\shared`. Po skončení můžeš příkaz ukončit pomocí `Ctrl+C` a zavřít divákův WoW.

### Příprava další kopie diváka

Použij izolovaný klient WoW 3.3.5a enUS build 12340. Vytvoř soubor `SpotlightDuet.lab` a znovu sestav `Data\patch-Z.MPQ` podle [návodu pro duet](duet.md#příprava-dalších-testovacích-kopií). Aktuální generátor označuje každý slot, aby jej šlo jednoznačně najít a vyměnit za běhu. Do `Interface\AddOns` diváka zkopíruj celou složku `source\tools\dance_capture\live_lab\SpotlightViewer`. Divák používá původní mapování `/dance` ze základní hry.

## Ověření

Na AI World Lab divák vstoupil do světa až po rozběhnutí dvou různých tanců a automaticky stáhl oba klipy. Každá postava měla vlastní aktivní slot. V 98 pozorováních za 30 sekund se fáze přehrávaná divákem lišila od času služby nejvýše o 31 ms. Po zastavení prvního tanečníka druhý pokračoval. Samostatně prošel i tok z panelu `/spotlight` od výběru MP4 přes ComfyUI a **Play dance** po ověřený soubor a přehrávání v klientu diváka.

Tato zkouška proběhla s dřívějším balíčkem a dvěma postavami `HumanMale` na jednom realmu. Aktuální klient používá stejné ID a čas přehrání pro všechny podporované kostry.
