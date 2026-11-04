# Galerie Spotlight

Na AI World Labu otevři [webovou galerii](http://192.168.0.248:9093/). Můžeš procházet klipy a stáhnout si výsledný soubor animace. Ve WoW otevři `/spotlight` → **Gallery**, klikni na **Download** u vybraného tance a pak ho vyber v **My dances**. Po načtení klikni na **Play dance**. Prohlížení a stahování používá stejnou galerii na webu i ve hře.

Importér každých pět sekund prochází výstupy Spotlightu v ComfyUI. Zpracuje i existující výstupy. Do galerie publikuje pouze hotové animace `*.motion.json`. Klip má ID podle SHA-256 výsledných dat a klient při stažení kontroluje shodu s ID. Když nový převod vytvoří shodný klip, galerie posune jeho stávající kartu mezi nejnovější a zobrazí čas posledního převodu.

## Nasazení s ComfyUI

Konfiguraci a postup pro Docker najdeš ve složce `server/`. Zápis do galerie vyžaduje token importéru. Čtení je dostupné na nastavené síťové adrese. [Nasazení galerie a importu](../../server/README.md#galerie-a-import-klipů)

Galerie ukládá klipy a metadata do SQLite na pojmenovaném Docker svazku `dances`. Klient ve výchozím nastavení používá hostitele z `realmlist.wtf` a port `9093`. Pro jinou adresu nastav `--gallery-url` při sestavení nebo `gallery_url` v `Spotlight/settings.json`. Klient používá stejnou adresu pro seznam i stažení klipu.
