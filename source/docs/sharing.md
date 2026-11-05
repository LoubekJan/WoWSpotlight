# Automatické sdílení tanců na labu

Po kliknutí na **Play dance** klient přehraje vlastní klip a oznámí jeho začátek službě Spotlight. Realm dál přenáší herní emoci. Klient diváka spojí oba údaje podle GUID postavy, stáhne klip a načte jej za běhu. Hráči na stejném realmu používají stejnou sdílecí službu.

- **ID klipu** je SHA-256 souboru s tancem. Každý divák ověří obsah proti tomuto ID i při načtení z místní mezipaměti.
- **ID přehrání** vznikne při každém spuštění, i když hráč znovu použije stejný klip. Služba k němu přiřadí GUID tanečníka a čas začátku. Podle něj naváže divák, který dorazí později, na aktuální část smyčky.
- **Sloty animací** jsou 69 pro běžný `/dance`, 156 pro vlastní tanec a 154 a 155 pro dva současně sledované tanečníky. Každý z dvaceti základních modelů má vlastní trojici slotů Spotlightu. Pohybem hráč ukončí vlastní tanec a sdílení. Příkaz `/dance` přepne na běžný tanec a ukončí sdílení.

V jednom klientu WoWSpotlight probíhá tvorba i sledování tanců automaticky po startu hry. Na AI World Labu si klient po načtení klipu k přehrání vyžádá oprávnění ke sdílení pro právě přihlášenou postavu. Realm jí doručí jednorázový ověřovací kód a doplněk jej předá pomocné aplikaci na pozadí. [Společný klient](player-files.md)

## Nastavení služby Spotlight

Aktuální postup pro relay je v [serverovém návodu](../../server/README.md#relay). Na AI World Labu je výchozí port relay `8765`. Klient použije hostitele z realmlistu, případně vlastní `relay_url` v `Spotlight/settings.json`. Pro automatické ověření je na labu zapnuté `relay_realm_auth`.

Pro technický test se samostatným tanečníkem a divákem je k dispozici [historický návod pro PoC](legacy-sharing.md).
