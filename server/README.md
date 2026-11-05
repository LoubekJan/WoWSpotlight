# Nasazení serveru WoWSpotlight

Server používá existující realm WoW 3.3.5a, instanci ComfyUI a tři služby na adrese dostupné hráčům. ComfyUI převádí videa, galerie nabízí hotové klipy a relay synchronizuje přehrávání. Stáhni celý repozitář a příkazy spouštěj z jeho kořene. Konfigurace nasazení je v `server/` a používá aktuální kód ze [`source/`](../source/README.md).

| Služba | Výchozí port klienta |
|---|---|
| ComfyUI | `8188` |
| Galerie | `9093` |
| Relay | `8765` |

Klient odvozuje hostitele z `Data/enUS/realmlist.wtf`. Pro služby na jiném hostiteli nebo portu nastav `comfy_url`, `gallery_url` a `relay_url` v klientském `Spotlight/settings.json`. Přepiš jen adresy, které se liší od výchozího nastavení.

## ComfyUI

1. Zkopíruj [`comfyui_spotlight`](../source/tools/dance_capture/comfyui_spotlight/) do `<ComfyUI>/custom_nodes/` a do Python prostředí ComfyUI nainstaluj `mediapipe==0.10.32`.
2. Ulož model `pose_landmarker_full.task` do `<ComfyUI>/custom_nodes/comfyui_spotlight/models/` nebo nastav `SPOTLIGHT_POSE_MODEL` na jeho absolutní cestu. Potom restartuj ComfyUI. [Model a podrobný postup](../source/docs/comfyui.md#instalace-uzlů-a-modelu)
3. V ComfyUI otevři [workflow Spotlight](../source/tools/dance_capture/Spotlight%20-%20Video%20to%20WoW%20Motion.json). Po úspěšném převodu je klip v `<ComfyUI>/output/spotlight/`. Pokud používáš samostatný worker, nasaď na něj stejný uzel a model.

## Galerie a import klipů

Vytvoř soubor `server/.env.gallery` podle [`gallery.env.example`](gallery.env.example). Nastav vlastní `SPOTLIGHT_GALLERY_TOKEN`, adresu rozhraní dostupnou hráčům a skutečnou cestu `SPOTLIGHT_COMFY_OUTPUT` k výstupům na Docker hostu. Importér ji potřebuje číst pod nastaveným UID a GID. Na Linuxu nastav souboru s tokenem oprávnění `0600`.

Náhodný token vytvoříš tímto příkazem.

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

```sh
docker compose -p wowspotlight-gallery --env-file server/.env.gallery \
  -f server/compose.yaml -f server/compose.comfy.yaml up -d --build
```

Otevři `http://<hostitel>:9093/`. Stav služby ověříš na `/healthz`. Galerie používá pojmenovaný Docker svazek `dances`. Importér přistupuje ke složce s klipy ComfyUI pouze pro čtení. Pro samostatnou galerii použij pouze `server/compose.yaml`.

## Relay

Pro běžné nasazení zkopíruj [`relay-actors.example.json`](relay-actors.example.json) do `server/relay-actors.json`. Klíč nahraď GUID skutečné postavy z realmu a hodnotu vlastním náhodným tokenem. Každé postavě přiřaď samostatný token. Hráč uloží svůj token do `Spotlight/relay.token`, nastaví výslovné `relay_url` a přepne `relay_realm_auth` na `false` v `Spotlight/settings.json`.

Spusť službu v Pythonu 3.12. Hodnotu `--bind` nastav na síťové rozhraní dostupné hráčům.

```sh
python3.12 source/tools/dance_capture/spotlight_relay.py \
  --actors server/relay-actors.json --data-dir artifacts/server/relay \
  --bind 0.0.0.0 --port 8765
```

Stav služby ověříš na `http://<hostitel>:8765/state`. Automatické ověření `--realm-proof` v AI World Labu závisí na jeho Docker kontejneru účtového webu s přístupem k privátní konzoli TrinityCore. Na tomto labu je klientské `relay_realm_auth` nastavené na `true`. [Podrobnosti ke sdílení](../source/docs/sharing.md#nastavení-služby-spotlight)
