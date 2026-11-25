# Hostinger Docker deployment

Compose project: `metadata-manager`. Host checkout: `/docker/metadata-manager`.
Application URL: https://metadata.187.52.127.215.sslip.io

The app runs as UID/GID 10001 using Gunicorn and WhiteNoise, with DEBUG disabled. SQLite, submissions and evidence live under `./data`, outside the image. The app has no public host port. An existing Caddy HTTPS gateway on the external `rodem-mes_mesnet` Docker network forwards this hostname to `metadata-manager-app:8000`. Only enable TRUST_PROXY with this restricted ingress arrangement.

## Install on this VPS

1. Clone the repository into `/docker/metadata-manager`.
2. Create `.env` with a random SECRET_KEY, the allowed hostname and localhost, and CSRF_TRUSTED_ORIGINS set to the HTTPS URL. Set file mode 600.
3. Restore the authorized DB and evidence backup into `data`, or create an empty data directory. Set ownership to 10001:10001 and mode 700.
4. Run `docker compose up -d --build`.
5. Back up the existing gateway Caddyfile, append the separate site from `Caddyfile.example`, validate, and gracefully reload Caddy. Never replace the other sites.
6. Verify container health, HTTPS login, static files, evidence and submission downloads.

For a fresh empty database, create the initial account interactively:

```sh
docker compose exec app python manage.py create_user admin --manager
```

The existing account is preserved when importing a DB; credentials are not part of the source or image. Local demo files are excluded from Docker build context.

## Updates and operations

```sh
cd /docker/metadata-manager
git pull --ff-only
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 app
```

Do not use `docker compose down -v`. Keep the `data` directory and private `.env` through redeploys. Preserve the initial import archive until recovery has been verified. To back up, stop app writes (or stop app) and run the backup management command with the same data bind mount; save DB and evidence together. Schedule backups during the maintenance window described in the root README.

Container resources: 512MB memory, 1 CPU; automatic restart unless explicitly stopped. Health endpoint checks the DB. App cookies have dedicated names to avoid collision with other services.

This deployment uses the existing VPS and gateway; it does not purchase hosting, change DNS zones, reset other services, or create a separate Traefik instance. The IP-based hostname can be replaced later by an owned domain.

References: [Hostinger project management](https://www.hostinger.com/support/hostinger-vps-how-to-manage-your-docker-projects/), [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [WhiteNoise Django setup](https://whitenoise.readthedocs.io/en/stable/django.html).

## Deployment verification — 2026-11-26

- Restored the existing local database and evidence with SHA-256 checks.
- Container reports healthy; HTTPS certificate validation succeeds.
- Verified real administrator login with CSRF, Secure session cookies, hashed static assets, all main pages, evidence download and existing submission download.
- Dedicated HTTPS hostname; HSTS is limited to this hostname (no includeSubDomains or preload).
- Deployment tests: 26 passing, including trusted HTTPS proxy handling and health endpoint.
