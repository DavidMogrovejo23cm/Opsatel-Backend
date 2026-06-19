FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates build-essential python3-dev chromium \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt package.json package-lock.json ./

RUN pip install --no-cache-dir -r requirements.txt
RUN npm ci --production

COPY . .

EXPOSE 8000
ENV PYTHONUNBUFFERED=1
COPY wait-for-db.py /usr/local/bin/wait-for-db.py
CMD ["python", "/usr/local/bin/wait-for-db.py"]
