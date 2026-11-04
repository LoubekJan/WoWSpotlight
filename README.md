# WoWSpotlight 1.0

WoWSpotlight přidává do World of Warcraft vlastní tance vytvořené z videa. V herním panelu `/spotlight` nahraješ MP4, vybereš hotový tanec z knihovny nebo galerie a spustíš ho tlačítkem **Play dance**. Spotlight přizpůsobí stejný klip kostře tanečníka a připraveným klientům v dosahu zobrazí správný tanec.

Podporovaný klient je **WoW 3.3.5a enUS, build 12340, pro Windows**. Tance fungují v základní podobě všech deseti hratelných ras a obou pohlaví. Běžný `/dance` má samostatný animační slot.

| Chci | Použiju |
|---|---|
| Hrát | [Hotové soubory v `client/`](client/) a [návod pro hráče](source/docs/player-files.md) |
| Nasadit služby | [Postup pro správce v `server/`](server/README.md) |
| Upravit kód nebo sestavit klienta | [Zdrojový kód v `source/`](source/) a [návod na sestavení](source/docs/player-files.md#sestavení-klienta-ze-zdrojů) |

## Hráč

1. Zavři WoW a zkopíruj celý obsah `client/` vedle svého `WoW.exe`.
2. Spusť `WoW.exe`, přihlas se na realm s nasazenými službami Spotlightu, přepni do režimu okna a zadej `/spotlight`.
3. Použij **Upload video** pro vytvoření tance nebo **Gallery** → **Download** pro stažení existujícího. V **My dances** vyber klip a klikni na **Play dance**.

Spotlight při startu použije hostitele z `Data\enUS\realmlist.wtf`. Výchozí porty jsou `8188` pro ComfyUI, `9093` pro galerii a `8765` pro sdílení ve hře. V `Spotlight\settings.json` můžeš jednotlivé adresy přepsat pomocí `comfy_url`, `gallery_url` a `relay_url`.
