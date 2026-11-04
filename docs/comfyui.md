# ComfyUI pro WoW Spotlight

Na AI World Lab byl převod ověřen s ComfyUI 0.25.0 a Pythonem 3.12.3. Pokud používáš už připravenou instanci labu, pokračuj [spuštěním ve hře](../README.md). Níže je postup pro vlastní instanci ComfyUI.

## Instalace uzlů a modelu

1. Zkopíruj celou složku `tools/dance_capture/comfyui_spotlight` z tohoto repozitáře do složky `custom_nodes` v instalaci ComfyUI. Výsledná cesta k doplňku má být `<ComfyUI>/custom_nodes/comfyui_spotlight/__init__.py`.
2. V prostředí Pythonu, ze kterého se spouští ComfyUI, spusť `python -m pip install mediapipe==0.10.32`. SciPy, NumPy, Pillow a PyAV jsou součástí standardních závislostí ComfyUI 0.25.0. Na Debianu a Ubuntu při chybě s chybějící knihovnou `libGLESv2.so.2` doinstaluj balíček `libgles2` do systému nebo obrazu workeru. [Závislosti ComfyUI 0.25.0](https://github.com/Comfy-Org/ComfyUI/blob/v0.25.0/requirements.txt)
3. Stáhni [MediaPipe Pose Landmarker Full](https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task) do `<ComfyUI>/custom_nodes/comfyui_spotlight/models/pose_landmarker_full.task`. Model můžeš uložit i jinam a nastavit proměnnou prostředí `SPOTLIGHT_POSE_MODEL` na absolutní cestu k souboru.
4. Restartuj ComfyUI. Pokud gateway posílá úlohy samostatnému workeru, uzly, model a závislosti musí mít worker. Pokud ComfyUI omezuje načítání vlastních uzlů podle seznamu, povol `comfyui_spotlight`.

MediaPipe v tomto PoC běží na CPU. Pokud ComfyUI obsluhuje GPU orchestrátor, spouští worker stejně jako pro ostatní workflow.

## Zkouška v ComfyUI

1. Otevři [Spotlight - Video to WoW Motion.json](../tools/dance_capture/Spotlight%20-%20Video%20to%20WoW%20Motion.json) v ComfyUI a v uzlu **Nahraj video** vyber vlastní MP4 s jedním člověkem, kterému je vidět celé tělo.
2. Klikni na **Run**. Workflow použije prvních 17,7 sekundy a obraz podle potřeby zmenší do 1280 × 720 na šířku nebo 720 × 1280 na výšku. Výsledkem jsou lokální rotace 20 kostí pro lidskou mužskou postavu.
3. V posledním uzlu klikni na **Download motion JSON**. Výstup se ukládá do `<ComfyUI>/output/spotlight/` jako `*.motion.json` ve formátu `wow-spotlight-motion`.

## Připojení hry

Adresu vlastní instance předej pomocné aplikaci volbou `--comfy-url`, například `--comfy-url http://127.0.0.1:8188`. Při použití vlastní gateway musí `POST /api/upload/image` přijmout MP4 v poli `image` a `POST /api/prompt` musí umožnit uzlu `LoadVideo` hned použít nově nahraný soubor. Pomocná aplikace čeká na výsledek přes `GET /api/history/{id}` a stáhne JSON přes `GET /api/view`. Tyto cesty poskytuje i standardní ComfyUI 0.25.0. [API ComfyUI](https://github.com/Comfy-Org/ComfyUI/blob/v0.25.0/server.py) · [Uzel LoadVideo](https://github.com/Comfy-Org/ComfyUI/blob/v0.25.0/comfy_extras/nodes_video.py)

Pro rychlou kontrolu po nasazení otevři `/api/object_info/SpotlightCapturePose` na adrese ComfyUI. Pokud vrátí popis uzlu, je uzel registrovaný. Úspěšný převod z herního panelu ověří i nahrání MP4, zařazení úlohy, stažení výsledku a přehrání.
