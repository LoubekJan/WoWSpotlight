FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY source/gallery/server.py source/gallery/import_comfy.py gallery/
COPY source/gallery/web/ gallery/web/
COPY source/tools/dance_capture/arm_motion.py source/tools/dance_capture/client_poc.py source/tools/dance_capture/spotlight_http.py source/tools/dance_capture/spotlight_library.py tools/dance_capture/
RUN mkdir /data && chown 10001:10001 /data

USER 10001:10001
EXPOSE 8780
ENTRYPOINT ["python", "-m", "gallery.server", "--bind", "0.0.0.0", "--port", "8780", "--data-dir", "/data"]
