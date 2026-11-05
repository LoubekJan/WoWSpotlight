# Zdrojový kód WoWSpotlightu

| Část | Umístění |
|---|---|
| Herní doplněk `/spotlight` | [SpotlightDanceLab](tools/dance_capture/live_lab/SpotlightDanceLab/) |
| Pomocná aplikace pro Windows | [Spouštěcí modul](tools/dance_capture/spotlight_client.py) a [bridge](tools/dance_capture/spotlight_bridge.py) |
| Převod videa na animaci | [Uzly ComfyUI](tools/dance_capture/comfyui_spotlight/) a [workflow](tools/dance_capture/Spotlight%20-%20Video%20to%20WoW%20Motion.json) |
| Galerie a sdílení | [Web a importér galerie](gallery/) a [relay](tools/dance_capture/spotlight_relay.py) |
| Sestavení klienta | [Postup sestavení](docs/player-files.md#sestavení-klienta-ze-zdrojů) |

Pro nasazení služeb použij [serverový návod](../server/README.md). Hotové soubory k instalaci do WoW jsou v [`client/`](../client/).

## Historické zkoušky

[Původní převod](tools/dance_capture/README.md), [Live Lab](tools/dance_capture/live_lab/README.md), [Duet](docs/duet.md) a [sdílení s oddělenými klienty](docs/legacy-sharing.md) popisují samostatné testy z vývoje prototypu.
