# Galerie Spotlight

Na AI World Labu otevři [webovou galerii](http://192.168.0.248:9093/). Můžeš procházet klipy a stáhnout si výsledný soubor animace. Ve WoW otevři `/spotlight` → **Gallery**, klikni na **Download** u vybraného tance a pak ho vyber v **My dances**. Po načtení klikni na **Play dance**. Prohlížení a stahování používá stejnou galerii na webu i ve hře.

Importér každých pět sekund prochází výstupy Spotlightu v ComfyUI. Zpracuje i existující výstupy. Do galerie publikuje pouze hotové animace `*.motion.json`. Klip má ID podle SHA-256 výsledných dat. Stejný obsah má v galerii jeden záznam a klient při stažení kontroluje shodu s ID.

## Nasazení s ComfyUI

Na Docker hostu připrav soubor `gallery/.env.gallery` s oprávněním `0600`. Pro `SPOTLIGHT_GALLERY_TOKEN` vygeneruj náhodný token, například příkazem `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Token používá importér pro zápis do galerie. Pro čtení je galerie přístupná na zvolené síťové adrese.

```dotenv
SPOTLIGHT_GALLERY_BIND=192.168.0.248
SPOTLIGHT_GALLERY_PORT=9093
SPOTLIGHT_COMFY_OUTPUT=/mnt/storage/ComfyUI/output/spotlight
SPOTLIGHT_COMFY_UID=1000
SPOTLIGHT_COMFY_GID=1000
```

Pro vlastní lab uprav adresu, složku a UID/GID podle svého ComfyUI. Importér potřebuje číst hotové soubory. Docker mu složku připojí pouze pro čtení.

Z kořene repozitáře spusť následující příkaz.

```sh
docker compose -p wowspotlight-gallery --env-file gallery/.env.gallery \
  -f gallery/compose.yaml -f gallery/compose.comfy.yaml up -d --build
```

Galerie ukládá klipy a metadata do SQLite na pojmenovaném Docker svazku `dances`. Adresu pro klienta nastav při sestavení přes `--gallery-url` nebo v `Spotlight/settings.json` pomocí `gallery_url`. Klient používá stejnou adresu pro seznam i stažení klipu.
