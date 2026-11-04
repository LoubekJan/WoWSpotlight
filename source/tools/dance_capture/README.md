# Zachycení tance z videa

Tento původní nástroj zpracuje místní video pomocí MediaPipe Pose Landmarker. Pro každý snímek uloží čas a odhad polohy 33 bodů těla. Výstup slouží jako vstup pro převod pohybu na kostru postavy ve WoW 3.3.5a.

Aktuální tok od výběru videa po přehrání ve hře popisuje [hlavní návod WoWSpotlight](../../../README.md).

## Spuštění ve Windows

Z kořene repozitáře spusť v PowerShellu následující příkazy. Nástroj je ověřený s Pythonem 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r source/tools/dance_capture/requirements.txt
Invoke-WebRequest 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task' -OutFile pose_landmarker_lite.task
.\.venv\Scripts\python.exe source/tools/dance_capture/extract_pose.py .\tanec.mp4 .\tanec.pose.json --model .\pose_landmarker_lite.task
```

Použij krátký klip s jedním tanečníkem, pevnou kamerou a celým tělem v záběru. Vstup může mít nejvýše 1 800 snímků a čas posledního snímku musí být pod 30 sekundami. Nástroj vypíše počet snímků, ve kterých model našel postavu.

## Výstup pro převod na kostru

- `format` je `mediapipe-pose-landmarks`, `version` je `1`.
- `frames` obsahuje dekódované snímky v časovém pořadí. `time_ms` je čas od prvního snímku.
- `pose.image` a `pose.world` obsahují body v pořadí MediaPipe. Každý bod má hodnoty `[x, y, z, visibility, presence]`. `image` používá souřadnice vztažené k obrazu, `world` odhad v metrech se středem mezi boky. [Popis modelu a bodů](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)
- Snímek bez detekce má `pose: null` a zachovává svůj čas. Celkový počet úspěšných detekcí je v `detected_frames`.

## Spotlight PoC v klientu WoW 3.3.5a

PoC přenáší změnu ohybu pravého lokte z videa na kost předloktí modelu HumanMale. Používá existující animační slot 211 a zachovává jeho ostatní animační stopy. Klip se musí vejít do 17,7sekundového slotu. Po konci klipu drží předloktí poslední zachycenou polohu až do konce slotu.

Nejprve nainstaluj [StormLib](live_lab/README.md#jednorázová-příprava). Generátory používají data klienta `C:\WoWModding\Client-Lab\Data`. Jinou cestu můžeš předat pomocí `--client-data`. Výstupy vytvářej mimo klienta.

```powershell
py -3.12 -B source/tools/dance_capture/client_poc.py .\tanec.pose.json .\patch-Z.MPQ
py -3.12 -B source/tools/dance_capture/preview_poc.py .\patch-enUS-Z.MPQ
```

1. Vypni oddělenou testovací kopii WoW 3.3.5a enUS. Do její složky `Data\enUS` přidej `patch-enUS-Z.MPQ`, který zapíná offline náhled. Spusť klienta a podívej se na siluetu vpravo v čase 417 ms. To je kontrolní vzorek s původní animací.
2. Vypni testovacího klienta, přidej `patch-Z.MPQ` do jeho složky `Data` a znovu ho spusť. Na stejném snímku porovnej pravé předloktí. Vlevo běží smyčka prvních 4,167 sekundy, což je délka ověřovacího vzorku.

Náhled využívá přihlašovací obrazovku a funguje bez účtu a připojení k realmu. Pro jiný vstup vyměň animační balíček při vypnutém klientu.

Ověřeno na buildu 12340. Ze 4,2sekundové ukázky tance a její časově obrácené verze vznikly dva balíčky s různými hodnotami ve 248 rotačních klíčích. V klientu má model v čase 417 ms s obráceným videem pravé předloktí viditelně níž než s původním videem. [Zdroj ukázky](https://www.tensorflow.org/hub/tutorials/movenet)
