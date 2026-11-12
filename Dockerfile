FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# Backup tooling (M4.5): rclone (crypt) from Debian, and pg_dump/pg_restore 16 copied from the
# official postgres:16 image (same Debian release) so they match the database server exactly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends rclone libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=postgres:16 /usr/lib/postgresql/16/bin/pg_dump /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
