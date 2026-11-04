# Automatické sdílení tanců na labu

Po kliknutí na **Play dance** klient přehraje vlastní klip a oznámí jeho začátek službě Spotlight. Realm dál přenáší herní emoci. Klient diváka spojí oba údaje podle GUID postavy, stáhne klip a načte jej za běhu. Hráči na stejném realmu používají stejnou sdílecí službu.

- **ID klipu** je SHA-256 souboru s tancem. Každý divák ověří obsah proti tomuto ID i při načtení z místní mezipaměti.
- **ID přehrání** vznikne při každém spuštění, i když hráč znovu použije stejný klip. Služba k němu přiřadí GUID tanečníka a čas začátku. Podle něj naváže divák, který dorazí později, na aktuální část smyčky.
- **Sloty animací** jsou 69 pro běžný `/dance`, 211 pro vlastní tanec a 154 a 155 pro dva současně sledované tanečníky. Načtení klipu pouze připraví slot 211. Pohybem hráč ukončí vlastní tanec a sdílení. Příkaz `/dance` přepne na běžný tanec a ukončí sdílení.

V jednom klientu WoWSpotlight probíhá tvorba i sledování tanců automaticky po startu hry. Na AI World Labu si klient po načtení klipu k přehrání vyžádá oprávnění ke sdílení pro právě přihlášenou postavu. Realm jí doručí jednorázový ověřovací kód a doplněk jej předá pomocné aplikaci na pozadí. Následující kroky patří k dřívější zkoušce s oddělenými klienty a ručními tokeny. [Společný klient](player-files.md)

## Tanečník

1. Použij připravený klient s doplňkem `SpotlightDanceLab` a mapováním `/dance` z [první instalace](../tools/dance_capture/live_lab/README.md). Na labu už jsou připravené `LiveActor` a obě kopie `Duet\ActorA` a `Duet\ActorB`.
2. Správce služby musí pro herní GUID této postavy nastavit token. Ulož jej jako jeden řádek do souboru, například `C:\WoWSpotlight\artifacts\share\moje-postava.token`. Každá postava má vlastní token.
3. V PowerShellu spusť následující příkaz. Na labu tento spouštěč už obsahuje adresu ComfyUI. Pro druhého tanečníka zadej jeho vlastní `--client-dir` a token.

   ```powershell
   & 'C:\WoWModding\SpotlightPoC\Start Spotlight.cmd' `
       --client-dir 'C:\WoWModding\SpotlightPoC\LiveActor' `
       --relay-url 'http://192.168.0.248:8765' `
       --relay-token-file 'C:\WoWSpotlight\artifacts\share\moje-postava.token'
   ```

4. Ve WoW v režimu okna otevři `/spotlight`, nahraj MP4 a po **Your dance is ready** klikni na **Play dance**. Pohybem postavy ukončíš sdílení. Před načtením dalšího klipu ukonči aktuální tanec.

Pro technickou zkoušku s hotovým souborem lze místo panelu spustit `spotlight_publish.py`. Předej PID již přihlášeného tanečníka, cestu k `*.motion.json`, `--client-dir`, `--relay-url` a `--relay-token-file`. Po hlášce **Ready for /dance** použij běžný `/dance`.

## Divák

1. Spusť `C:\WoWModding\SpotlightPoC\Duet\Observer\WoW.exe` a nech ho na **výběru postavy**.
2. V PowerShellu v kořeni repozitáře spusť následující blok. Jakmile vypíše **Spotlight viewer is ready**, vstup do světa. Okno PowerShellu nech otevřené.

   ```powershell
   $dir = 'C:\WoWModding\SpotlightPoC\Duet\Observer'
   $wow = @(Get-Process WoW -ErrorAction SilentlyContinue |
       Where-Object Path -eq (Join-Path $dir 'WoW.exe'))
   if ($wow.Count -ne 1) { throw "Spusť právě jedno WoW z $dir." }
   py -3.12 -B .\tools\dance_capture\spotlight_viewer.py $wow[0].Id `
       --client-dir $dir --relay-url 'http://192.168.0.248:8765'
   ```

3. Přijď k tanečníkům. Klient stáhne potřebné klipy sám. Stažené soubory najdeš pod `Observer\Spotlight\shared`. Po skončení můžeš příkaz ukončit pomocí `Ctrl+C` a zavřít divákův WoW.

### Příprava další kopie diváka

Použij izolovaný klient WoW 3.3.5a enUS build 12340. Vytvoř soubor `SpotlightDuet.lab` a znovu sestav `Data\patch-Z.MPQ` podle [návodu pro duet](duet.md#příprava-dalších-testovacích-kopií). Aktuální generátor označuje každý slot, aby jej šlo jednoznačně najít a vyměnit za běhu. Do `Interface\AddOns` diváka zkopíruj celou složku `tools\dance_capture\live_lab\SpotlightViewer`. Divák používá původní mapování `/dance` ze základní hry.

## Nastavení služby Spotlight

Na AI World Lab běží `wowspotlight-relay.service` na adrese `http://192.168.0.248:8765`. Nastavení tanečníků je na serveru v `~/.local/share/wowspotlight/config/actors.json` pod účtem služby. Správce přidá GUID ve tvaru `0x` a 16 hexadecimálních číslic a náhodný token pro tuto postavu. Po úpravě restartuje službu. GUID přihlášené postavy lze přečíst přes `duet_select.py status <PID> --client-dir <cesta>` v poli `local_player_guid`.

Pro automatické ověření zapni službu s volbou `--realm-proof`. Proměnná `SPOTLIGHT_REALM_SOAP_CONTAINER` ukazuje na kontejner účtového webu labu s existujícím přístupem k privátní konzoli TrinityCore. Kód platí 75 sekund a vydané oprávnění má rozsah jedné postavy. V klientském `Spotlight/settings.json` se tento režim zapíná pomocí `relay_realm_auth`. Služba je určená pro síť AI World Labu.

Pro jiný lab spusť `tools/dance_capture/spotlight_relay.py --actors <actors.json> --data-dir <uložiště> --bind <adresa> --port 8765`. Soubor `actors.json` je JSON objekt mapující GUID na jedinečný token o délce 16 až 128 znaků z množiny `A–Z a–z 0–9 _ -`. Služba používá Python 3.12 a ukládá ověřené soubory JSON podle SHA-256. Aktivní tance jsou dočasné a klient tanečníka je pravidelně obnovuje. Diváci čtou stav a klipy bez tokenu. Nasazení na labu je určené pro jeho interní síť.

## Ověření

Na AI World Lab divák vstoupil do světa až po rozběhnutí dvou různých tanců a automaticky stáhl oba klipy. Každá postava měla vlastní aktivní slot. V 98 pozorováních za 30 sekund se fáze přehrávaná divákem lišila od času služby nejvýše o 31 ms. Po zastavení prvního tanečníka druhý pokračoval. Samostatně prošel i tok z panelu `/spotlight` od výběru MP4 přes ComfyUI a **Play dance** po ověřený soubor a přehrávání v klientu diváka.

Zkouška pokrývá dvě současné postavy `HumanMale` na jednom realmu. Klipy stáhne připravený klient se spuštěnou pomocnou aplikací.
