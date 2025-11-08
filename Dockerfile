# ---- Base image ----
FROM python:3.11-slim

# Prevent interactive tz/data prompts
ENV DEBIAN_FRONTEND=noninteractive         PYTHONDONTWRITEBYTECODE=1         PYTHONUNBUFFERED=1

# ---- System deps ----
RUN apt-get update && apt-get install -y --no-install-recommends         chromium chromium-driver xvfb         fonts-liberation fonts-dejavu-core ca-certificates tini         && rm -rf /var/lib/apt/lists/*

# Make sure chromium is on PATH for undetected-chromedriver
ENV CHROME_BIN=/usr/bin/chromium         CHROMEDRIVER_PATH=/usr/bin/chromedriver

# ---- App ----
WORKDIR /app
COPY . /app

# ---- Python deps ----
# If you already have a requirements.txt in repo, this will use it.
# Otherwise the one we create will be used.
RUN pip install --no-cache-dir --upgrade pip         && pip install --no-cache-dir -r requirements.txt

# Flask/Render expects to listen on $PORT
ENV PORT=10000         FLASK_ENV=production

# Results dir (used by app.py)
RUN mkdir -p /app/results

# ---- Runtime ----
# We run Gunicorn wrapped by Xvfb so Selenium/Chrome can run without changing your code
# Note: Render will send SIGTERM; use tini as init to reap zombies.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "gunicorn -k gthread -w 2 -b 0.0.0.0:${PORT} app:app"]
