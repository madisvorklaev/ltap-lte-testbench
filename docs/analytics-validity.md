# Analytics Validity

Analytics must not mix incompatible test definitions.

Default grouping requires:

- identical protocol hash;
- compatible result schema version;
- compatible measurement implementation version;
- completed and comparison-eligible runs;
- valid route and receiver confirmation;
- sufficient environment metadata.

Current implementation status:

- protocol hashes are seeded and persisted;
- analytics filters expose protocol hashes;
- incompatible selected protocol hashes produce an inconclusive warning;
- receiver-side UDP delivery is preferred over sender rate;
- video dual-link union/rescue metrics are stored when available;
- summary aggregates include sample count, median, percentiles, and spread.

Remaining work:

- baseline/candidate selectors;
- paired experiment blocks;
- bootstrap confidence intervals;
- practical-effect thresholds;
- time-of-night matching;
- persisted loaded latency and radio sample completeness;
- explicit `LIKELY_IMPROVEMENT` and `LIKELY_REGRESSION` decisions.

Until that work is complete, analytics can show distributions and exclusion
reasons but should avoid causal claims.
