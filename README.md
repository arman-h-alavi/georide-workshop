# GeoRide — Docker Compose Workshop

GeoRide is an educational ride-request backend demonstrating a Flask API, a Go location service, an asynchronous RabbitMQ matcher, PostgreSQL persistence, Redis geospatial queries, and metrics/logging infrastructure.

## Quick start

Requirements: Docker Engine and Docker Compose v2 on Linux.

```bash
cp .env.example .env
nano .env                 # set local-only passwords (all 5 variables are required, including RABBITMQ_USER and RABBITMQ_PASSWORD)

docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Check API health:

```bash
curl -i http://localhost/health
```

Register a rider:

```bash
curl -sS -X POST http://localhost/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"Workshop Rider","type":"rider"}'
```

Use the returned `user_id` to request a ride:

```bash
curl -sS -X POST http://localhost/request_ride \
  -H 'Content-Type: application/json' \
  -d '{"rider_id":4,"latitude":34.0522,"longitude":-118.2437}'
```

Replace `4` with the ID returned by registration, then poll the returned trip ID:

```bash
curl -sS http://localhost/trip/TRIP_ID
```

The request is asynchronous. Its status may initially be `requested`, then become `assigned` or `cancelled` depending on whether a simulated driver is found.

## Main services

- **Nginx** exposes HTTP on port `80` and forwards requests to the API.
- **PostgreSQL** stores users and trip records.
- **RabbitMQ** queues ride requests between the API and matcher.
- **Redis** stores live driver coordinates for geospatial lookup by the location service.
- **Prometheus** scrapes configured numerical metrics.
- **Promtail** collects Docker logs and ships them to **Loki**.

The service relationship diagram is in [docs/service-relationships.png](docs/service-relationships.png) (source: `docs/service-relationships.dot`).

## Useful local interfaces

| Interface | URL |
|---|---|
| API through Nginx | http://localhost |
| RabbitMQ management | http://localhost:15672 |
| Prometheus | http://localhost:9090 |
| cAdvisor | http://localhost:8080 |
| Grafana | http://localhost:3000 |
| Loki readiness | http://localhost:3100/ready |

Credentials are configured locally in `.env`; do not commit that file. Prometheus is configured to scrape itself, cAdvisor, Node Exporter, and the location service. PostgreSQL, RabbitMQ, Nginx, Loki, and Promtail do not currently have dedicated Prometheus exporters configured.

## CI/CD

`.github/workflows/ci-cd.yml` validates Compose configuration, checks Python syntax, resolves Go dependencies and runs Go tests, builds custom service images, and publishes images to GitHub Container Registry (GHCR) after successful pushes to `main`. Pull requests validate/build but do not publish.

## Stop the stack

```bash
docker compose down
```

This preserves named volumes. Use `docker compose down -v` only if you intentionally want to delete persisted database, metrics, Grafana, and Loki data.
