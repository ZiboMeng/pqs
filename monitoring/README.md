# Phase 3 monitoring

`phase3-monitoring.yaml` records the monitor-only cadence and commands. The supervisor
persists a heartbeat and evaluates the frozen `config/alerts.yaml` policy every minute.
If an existing heartbeat shows a gap over the configured alert threshold after restart,
it emits/deduplicates `missed_schedule` in the durable local sink.

Liveness means the monitor loop is fresh and healthy. Readiness is intentionally stricter
and can remain failed while the container is alive (for example before runtime/broker
state initialization or during a global pause). No metric or alert can return
`ready_for_live=true` in Phase 3.

The external notification adapter contract exists, but no notification credential or
remote sink is configured. Operators must inspect the local alert DB/control CLI until a
separately authorized adapter is supplied.
