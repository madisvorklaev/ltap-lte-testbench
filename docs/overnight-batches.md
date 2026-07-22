# Overnight Batches

An overnight batch is a persistent series of benchmark attempts.

## Counts

- `target_valid_runs`: number of comparable runs desired.
- `max_attempts`: maximum started attempts, including invalid and failed ones.
- valid run: completed and comparison-eligible.
- invalid run: completed or failed but not eligible for comparison.
- skipped attempt: preconditions failed before traffic started.

Invalid and skipped attempts remain visible. They count toward `max_attempts`,
but not toward `target_valid_runs`.

## Stop Rules

A batch completes when the valid target is reached.

A batch also completes with `deadline_reached` when a deadline is reached before
the target. This is not treated as failure.

A batch fails when `max_attempts` is reached before the valid target.

A batch pauses after too many consecutive infrastructure failures, after restart
recovery that requires operator review, or when measurement code drifts
mid-batch.

At batch creation/start, the runner stores the expected protocol hash,
application version, and application Git commit. During execution it also stores
the first observed test-node version. Later attempts are paused rather than
continued when these controlled measurement fields change. Current pause reason
codes include:

- `APPLICATION_VERSION_CHANGED`
- `TEST_NODE_VERSION_CHANGED`
- `PROTOCOL_HASH_CHANGED`

## Cooldown And Stabilization

Between attempts, the runner waits the configured cooldown. Cancellation remains
responsive during this wait.

Before creating a traffic run, the runner checks that the configured LTE paths
remain registered for the protocol's stabilization window. If not, the attempt is
marked skipped with a machine-readable outcome code such as
`MODEM_NOT_REGISTERED`.

## Test-Node Reservations

For runs using a configured test node, the worker reserves the node before
traffic starts and sends a reservation token with TCP, UDP, and video traffic.
The reservation TTL is derived from the estimated traffic plan plus cleanup
margin. During active runs, the worker renews the reservation every
`min(300 seconds, ttl / 3)`.

If renewal fails, traffic cancellation is requested, the run is marked
comparison-ineligible, and the exclusion reason is `RESERVATION_LOST`.

## Recovery

After a controller restart, active batch attempts are reconciled. Non-terminal
linked runs are marked interrupted, the attempt is marked failed with
`WORKER_RESTARTED`, and the batch is paused.

The operator should review the batch before resuming.

## Experiment Design

One overnight batch for one configuration measures variance and stability. It
does not prove another configuration is better.

For causal comparison, use counterbalanced runs:

- A, B, A, B blocks when manual changes are practical;
- or night 1 A, night 2 B, night 3 B, night 4 A.

Avoid comparing all A tests from one time period with all B tests from another
without a time-of-night warning.
