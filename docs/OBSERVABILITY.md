# Observability

## Endpoints

- `GET /health/live`
  - Liveness probe.
  - Returns service identity and server time.
- `GET /health/ready`
  - Readiness probe.
  - Checks database connectivity and pipeline status source availability.
  - Returns `200` when DB is ready, `503` when degraded.
- `GET /health/pipeline`
  - Operational status for Parsl pipeline.
  - Includes stage, task, run id and genome accession when detected.

## Request timing

- Middleware: `tpweb.middleware.observability.RequestTimingMiddleware`.
- Adds response header: `X-Request-Duration-Ms`.
- Logs request completion with method, path, status code and duration.

## Recommendations

1. Scrape `health/*` endpoints from infra monitoring.
2. Add alerting for repeated `ready=503`.
3. Export request timings to metrics backend (Prometheus/OpenTelemetry).
4. Track pipeline stage duration by run id for throughput tuning.
