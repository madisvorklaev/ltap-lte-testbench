# Live Device Safety

No live router changes have been made by this repository.

Rules for later MikroTik work:

1. Discover read-only state before changing anything.
2. Save `/export hide-sensitive`, firmware/version data, LTE inventory, rules, routes, and relevant connection tracking.
3. Disable FastTrack for benchmark runs only through a recorded temporary plan.
4. Clear only test-port connection tracking entries.
5. Restore original state after cancellation, failure, or completion.
6. If restoration fails, stop and emit exact recovery commands.

The controller web service must not run as root and binds to localhost by default.
