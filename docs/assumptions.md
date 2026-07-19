# Assumptions

- The router is currently disconnected, so live MikroTik validation is deferred.
- GitHub CLI is installed but not authenticated on this controller at project start.
- The initial controller runs on the same Linux computer as OpenClaw.
- FastTrack must be treated as a hard preflight risk for MikroTik benchmark runs.
- Ethernet carrier loss invalidates live LTE-path results because the controller may fall back to Wi-Fi.
- Until video parameters are known, load plans use configurable example bitrates only.
