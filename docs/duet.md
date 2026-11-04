# Duet na testovacím realmu

Zkouška přiřadí dvěma lidským mužským postavám dva hotové klipy. Obě spustí běžný `/dance`. Izolovaný klient diváka podle GUID každé postavy vybere animaci z jiného slotu. Přiřazení platí pro běžící proces diváka a restart je smaže.

## Připravená zkouška

Na počítači s AI World Lab jsou tři oddělené kopie klienta pod `C:\WoWModding\SpotlightPoC\Duet`. Každá má vlastní `WoW.exe` a konfiguraci. Divák už má oba ukázkové klipy v klientském balíčku.

1. Spusť `ActorA\WoW.exe`, `ActorB\WoW.exe` a `Observer\WoW.exe`. Použij tři účty. Tanečníci musí být lidští muži a musí už být ve světě. **Diváka nech na obrazovce výběru postavy.**
2. Otevři PowerShell v kořeni repozitáře a spusť tento blok. Najde procesy podle přesných cest, z klientů tanečníků přečte jejich herní ID a nastaví přiřazení v divákovi.

   ```powershell
   $duet = 'C:\WoWModding\SpotlightPoC\Duet'
   $tool = '.\tools\dance_capture\duet_select.py'
   $clients = @{}
   foreach ($role in 'ActorA', 'ActorB', 'Observer') {
       $dir = Join-Path $duet $role
       $wow = @(Get-Process WoW -ErrorAction SilentlyContinue |
           Where-Object Path -eq (Join-Path $dir 'WoW.exe'))
       if ($wow.Count -ne 1) { throw "Spusť právě jedno WoW z $dir." }
       $clients[$role] = @{ Id = $wow[0].Id; Dir = $dir }
   }
   $guids = @{}
   foreach ($role in 'ActorA', 'ActorB') {
       $client = $clients[$role]
       $json = py -3.12 -B $tool status $client.Id --client-dir $client.Dir
       if ($LASTEXITCODE -ne 0) { throw "Nepodařilo se přečíst ID postavy v $role." }
       $guid = ($json | ConvertFrom-Json).local_player_guid
       if ($guid -eq '0x0000000000000000') { throw "Postava v $role musí být ve světě." }
       $guids[$role] = $guid
   }
   $observer = $clients['Observer']
   py -3.12 -B $tool install $observer.Id --client-dir $observer.Dir `
       --actor "$($guids['ActorA'])=211" --actor "$($guids['ActorB'])=154"
   if ($LASTEXITCODE -ne 0) { throw 'Přiřazení klipů selhalo.' }
   ```

3. Vstup do světa v okně diváka a rozestav tanečníky před něj. U obou zadej `/dance`. Z pohledu diváka první tanečník mává levou rukou a druhý pravou. Popojdi v okně prvního tanečníka. Jeho tanec skončí a druhý pokračuje.
4. Stav ověříš ve stejném PowerShellu. Při souběhu je `active_animation` u prvního tanečníka `211` a u druhého `154`. Po ukončení prvního klesne jeho `emote_state` na `0`, zatímco druhý stále používá `154`.

   ```powershell
   py -3.12 -B $tool status $observer.Id --client-dir $observer.Dir
   ```

Na AI World Lab obě postavy v jednom klientu diváka současně používaly různé instance modelu a sekvence `144` a `156`. Po pohybu první postavy její aktivní animace přešla na `0` a druhá zůstala na `154`. Zkouška souběhu prošla také po restartu diváka s původním mapováním `/dance`.

## Příprava dalších testovacích kopií

Použij oddělené kopie WoW 3.3.5a enUS build 12340 z [návodu pro klienta](../tools/dance_capture/live_lab/README.md). Potřebuješ místní StormLib. Z kořene tohoto repozitáře sestav dva klipy a balíček. Výstupní MPQ musí mít novou cestu.

```powershell
py -3.12 -B .\tools\dance_capture\make_duet_clips.py .\artifacts\duet
py -3.12 -B .\tools\dance_capture\duet_assets.py `
    .\artifacts\duet\left-arm.motion.json .\artifacts\duet\right-arm.motion.json `
    .\artifacts\duet\patch-Z.MPQ --client-data 'C:\WoWModding\Client-Lab\Data'
```

Do složky `Data` vypnutého diváka vlož `patch-Z.MPQ`. Pokud už tento název používá jiná úprava, vyhraď pro duet vlastní kopii. Do kořene každé z těchto tří testovacích kopií vedle `WoW.exe` ulož soubor `SpotlightDuet.lab` s jediným řádkem `WoWSpotlight duet lab`. Skript marker kontroluje společně s cestou procesu a kontrolním součtem klienta.

## Náhled bez účtů

Na připraveném počítači otevři `C:\WoWModding\SpotlightPoC\DuetPreview\WoW.exe`. Na přihlašovací obrazovce se zobrazí oba pohyby vedle sebe. Kliknutí na model jeho animaci pozastaví nebo obnoví.

Pro vlastní kopii použij stejný `Data\patch-Z.MPQ` a sestav ještě balíček pro přihlašovací obrazovku. `patch-enUS-Z.MPQ` patří do `Data\enUS` samostatné vypnuté kopie pro náhled, kde je tento název volný.

```powershell
py -3.12 -B .\tools\dance_capture\duet_preview.py `
    .\artifacts\duet\patch-enUS-Z.MPQ --client-data 'C:\WoWModding\Client-Lab\Data'
```

Duet používá dva předem sestavené sloty a ruční přiřazení ke dvěma postavám. Vlastní přehrávání tanečníků dál řídí jejich klient. Automatické doručení klipů do klienta diváka je další milník.
