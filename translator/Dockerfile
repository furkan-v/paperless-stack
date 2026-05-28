FROM python:3.12-slim

# langdetect is a small statistical language detector — pure-Python, no network calls.
RUN pip install --no-cache-dir langdetect==1.0.9

WORKDIR /app
COPY translate.py /app/translate.py
# `prompts/` is bind-mounted from the host at runtime via compose.yaml; this
# COPY is a fallback default so the image is still runnable without the mount.
COPY prompts/ /app/prompts/

CMD ["python", "-u", "translate.py"]
