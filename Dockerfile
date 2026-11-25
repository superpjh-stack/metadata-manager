FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
COPY . .
RUN mkdir -p /data/media /app/staticfiles && chown -R app:app /data /app/staticfiles
USER app
EXPOSE 8000
ENTRYPOINT ["sh", "/app/deploy/entrypoint.sh"]
