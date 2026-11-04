# Příprava klienta a zkouška s divákem

## Jednorázová příprava

1. Nainstaluj **64bitový Python 3.12 pro Windows** s Python Launcherem a podporou Tcl/Tk. V PowerShellu ověř `py -3.12 --version`.
2. Připrav oddělenou testovací kopii WoW **3.3.5a enUS build 12340** a nastav připojení k testovacímu realmu. Výchozí složka je `C:\WoWModding\SpotlightPoC\LiveActor`. Pro zkoušku s divákem připrav druhou kopii `LiveObserver`. Skripty kontrolují přesnou verzi `WoW.exe` a potřebných dat.
3. Stáhni [StormLib pro Windows](https://github.com/ladislav-zezula/StormLib/releases/download/v9.40/stormlib_dll.zip). Z archivu vezmi `x64\StormLib.dll` a ulož ji do `source\tools\dance_capture\vendor\StormLib.dll` v tomto repozitáři. Složku `vendor` v případě potřeby vytvoř.
4. Vypni testovací klienty a spusť následující blok z kořene repozitáře v PowerShellu. Cesty v prvních řádcích odpovídají již používané instalaci. Pro vlastní instalaci je uprav. Skript vytvoří balíček v `artifacts` mimo klienta a doplněk zkopíruje do `Interface\AddOns`. Pokud `Data\enUS\patch-enUS-Z.MPQ` ve tvém klientu už slouží jiné úpravě, vyhraď pro zkoušku samostatnou kopii.

   ```powershell
   $actor = 'C:\WoWModding\SpotlightPoC\LiveActor'
   $observer = 'C:\WoWModding\SpotlightPoC\LiveObserver' # Pro jediného hráče použij $null.
   $package = New-Item -ItemType Directory -Force '.\artifacts\install\live\Data\enUS'
   $patch = Join-Path $package.FullName 'patch-enUS-Z.MPQ'
   if (-not (Test-Path -LiteralPath $patch)) {
       py -3.12 -B '.\source\tools\dance_capture\live_setup.py' $patch --client-data (Join-Path $actor 'Data')
       if ($LASTEXITCODE -ne 0) { throw 'Sestavení klientského balíčku selhalo.' }
   }
   foreach ($client in @($actor, $observer).Where({ $_ })) {
       $addons = Join-Path $client 'Interface\AddOns'
       New-Item -ItemType Directory -Force $addons | Out-Null
       Copy-Item -LiteralPath '.\source\tools\dance_capture\live_lab\SpotlightDanceLab' -Destination $addons -Recurse -Force
       $installed = Join-Path $client 'Data\enUS\patch-enUS-Z.MPQ'
       if (Test-Path -LiteralPath $installed) {
           Write-Host "Balíček už existuje. Ověř jeho původ před případnou výměnou: $installed"
       } else {
           Copy-Item -LiteralPath $patch -Destination $installed
       }
   }
   ```

   Balíček mapuje běžný herní tanec na slot 211. Doplněk drží slot připravený v paměti a po stisku **Play dance** spustí herní emoci `/dance`.
5. Připrav [ComfyUI](../../../docs/comfyui.md) a z kořene projektu spusť `& '.\source\Start Spotlight.cmd' --client-dir $actor --comfy-url 'http://192.168.0.248:8188'`. Přihlas se za lidskou mužskou postavu, nech WoW v režimu okna a zadej `/spotlight`.

## Ruční ověření s divákem

1. Přihlas oba klienty na stejný testovací realm a postav postavy vedle sebe. Tanečník musí být lidský muž. V `LiveActor` vytvoř tanec přes `/spotlight`. Jakmile panel oznámí dokončení, soubor je v `LiveActor\Spotlight\active.pose.json`.
2. V PowerShellu otevřeném v kořeni repozitáře spusť hlídač pro `LiveObserver`. Sleduje soubor `ManualDemo\Observer\active.pose.json`. Pro čistý test nech tuto složku před spuštěním prázdnou a použij čerstvě spuštěného diváka.

   ```powershell
   $lab = 'C:\WoWModding\SpotlightPoC'
   $client = Join-Path $lab 'LiveObserver'
   $folder = Join-Path $lab 'ManualDemo\Observer'
   New-Item -ItemType Directory -Force $folder | Out-Null
   $active = Join-Path $folder 'active.pose.json'
   $wow = @(Get-Process WoW | Where-Object Path -eq (Join-Path $client 'WoW.exe'))
   if ($wow.Count -ne 1) { throw 'Spusť právě jedno WoW z LiveObserver.' }
   py -3.12 -B '.\source\tools\dance_capture\watch_live.py' $wow[0].Id $active --client-dir $client
   ```

3. U tanečníka klikni na **Play dance**. V klientu diváka sleduj tanečníka s výchozím pohybem. Potom v Průzkumníku zkopíruj `LiveActor\Spotlight\active.pose.json` do `ManualDemo\Observer`. Když hlídač vypíše `animation_sha256`, divák vidí nový pohyb i během probíhajícího tance. Stejný soubor lze stáhnout z HTTP úložiště. Ulož ho vedle cíle pod dočasným jménem a po dokončení ho přejmenuj na `active.pose.json`.

   ```powershell
   $clipUrl = 'https://example.com/active.pose.json' # Nahraď skutečnou adresou klipu.
   $folder = 'C:\WoWModding\SpotlightPoC\ManualDemo\Observer'
   $temp = Join-Path $folder 'download.tmp'
   $active = Join-Path $folder 'active.pose.json'
   Invoke-WebRequest $clipUrl -OutFile $temp -ErrorAction Stop
   py -3.12 -B -c 'from pathlib import Path; import sys; Path(sys.argv[1]).replace(sys.argv[2])' $temp $active
   ```

4. Hlídač ukončíš pomocí `Ctrl+C`. Běžící WoW drží poslední načtený klip v paměti do restartu nebo další výměny.

Při zkoušce na realmu dvě instance klienta načetly tentýž klip a vykázaly shodný hash. Divák viděl výměnu pohybu vzdálené postavy v už spuštěném tanci. Přenos souboru přes HTTP byl ověřen mezi dvěma instancemi na jednom počítači. Pozdější zkouška ověřila i celý tok od výběru MP4 přes ComfyUI po přehrání na postavě.
