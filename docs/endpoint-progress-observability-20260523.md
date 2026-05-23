# Endpoint progress and PAC observability

Version: 1.0.333

## Endpoint command progress

Endpoint operations now open a live progress modal after they are queued.  This applies to direct commands, Node.js install, pi.dev install, endpoint update, and maintenance jobs.

The modal shows:

- job id and endpoint id
- current status
- execution mode and shell
- created/updated timestamps
- exit code
- operation metadata
- command or managed operation payload
- output/error when the endpoint reports completion
- progress events associated with the job

The Endpoints page also has a **Details** action on each endpoint card.  The details modal shows identity, pi.dev command-channel state, recent endpoint jobs, raw metadata, raw capabilities, and controller observability location.

## Internal logging

PAC now configures local rotating logs using Python's standard `logging` package and `logging.handlers.RotatingFileHandler`.

Default files:

- `${PACP_HOME}/logs/pac-controller.log`
- `${PACP_HOME}/logs/pac-audit.log`

Default rotation:

- `PAC_LOG_MAX_BYTES=10485760`
- `PAC_LOG_BACKUP_COUNT=7`
- `PAC_LOG_LEVEL=INFO`

This avoids adding a heavy monitoring dependency while giving PAC a stable local diagnostic base.  The files can later be shipped to Loki, OpenTelemetry Collector, Vector, Fluent Bit, or any other centralized system.

## APIs

- `GET /v1/runner-jobs/{job_id}` returns job detail, endpoint detail, and related progress events.
- `GET /v1/system/observability` returns logging backend, rotation settings, log paths, and runtime metadata.
- `GET /v1/system/logs/tail?name=controller|audit&limit=8000` returns a bounded log tail.

## Design rule

Endpoint actions should not silently queue work and disappear.  Any action that queues a job should open a progress modal or show a clear result surface with the job id and current state.
