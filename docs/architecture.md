# Architecture

The controller is a single-host FastAPI application with a SQLite database and a separate worker module. The MVP runs jobs in-process for local development; the database state model is designed so the worker can be split into a systemd service without changing API contracts.

```text
Browser / CLI / OpenClaw
  -> FastAPI web and REST service
  -> SQLite profile, run, event, artifact store
  -> Worker state machine
  -> Router adapter, traffic tools, telemetry collectors, test-node API
```

Router adapters are separated from the run engine:

- `GenericRouterAdapter`: no RouterOS dependency; transport-only tests.
- `FakeRouterAdapter`: deterministic CI simulation.
- `MikroTikRouterAdapter`: read-only discovery and safety checks first; live write support will be added behind explicit preparation plans.
