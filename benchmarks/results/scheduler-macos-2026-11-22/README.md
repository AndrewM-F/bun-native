# Idle-receive scheduler: macOS paired steady-update experiment

On a physical Apple M2 Max, macOS 27.2.1 (26B131), Rust 1.98.1 and the repository release profile, compare baseline main `492f2e0e9cc15cd2d95958e91dd579383b81ded1` with candidate host source from `de8521dc5af6f1d08a62decf702ac4d04f2eb103`. Both hosts were built in the same checkout with the same toolchain; their SHA-256 values are `486b7481feafe7c9f0cda8ada8e65ffc2d6acbae934b58eb85b451e7fa341a5e` (baseline) and `d8cf6d73f96fa4b09d9e35ed31e1264e6a327948e5839802a2ee61d6bcd29eb2` (candidate). The same application executable was used throughout, SHA-256 `7a49951798da843eac4d6ede4341c31c9537da61683eb0a83bb2d5d2a9d1b8c7`; the repository inspectors reported a compiled program with JIT unused.

Each process executed a Core workload with 1,000 sequential signal updates, 10 rotations, one mount and two rows. Four warmups preceded each set of 10 fresh-process AB/BA pairs. The repeat reversed the initial order. The A/A control used the same baseline executable for both labels. All 72 launches passed workload, retention and cleanup assertions. Tracing was disabled. Results measure acknowledgement through the public core, not input-to-visible-output or presentation.

The table shows per-process p95 and total acknowledgement time, with median paired candidate-minus-baseline differences. Intervals are 10,000 paired-bootstrap resamples of the median, seed 20261122; negative favors the candidate. These endpoints were selected after an earlier exploratory experiment. Other load and power were uncontrolled: one-minute load averages reached approximately 76 during this run, and same-machine pairs may be temporally correlated. This is not a cross-platform or market comparison.

| Cohort                | p95 baseline / candidate | Paired p95 difference [95% interval] | 1,000-update total difference [95% interval] | p95 candidate faster |
| --------------------- | -----------------------: | -----------------------------------: | -------------------------------------------: | -------------------: |
| First                 |         2.052 / 0.473 ms |           -1.578 ms [-1.646, -1.415] |                   -160.7 ms [-214.8, -145.1] |                10/10 |
| Reversed-order repeat |         1.996 / 0.341 ms |           -1.530 ms [-1.818, -1.451] |                   -187.5 ms [-302.1, -105.1] |                10/10 |
| Identical-host A/A    |         1.844 / 1.899 ms |           +0.071 ms [-0.014, +0.090] |                       -1.5 ms [-21.5, +30.1] |                 2/10 |

[Original launch reports, process summaries and harnesses](raw.tar.gz) are retained, SHA-256 `cfbeb10e59b424932c7ec79a1f6005bb4c574eff9bb6df94064b0bfc5f406f96`. Host and application executables are not included. The scripts accept paths to those exact executables and a new output directory. Each report retains its original complete samples and outcomes; summaries retain load, binary hashes and ordering.

The result supports the steady-update lead on this machine. It does not establish Linux performance or input/paint fairness under sustained queue saturation. The unchanged native Linux scheduling test, cross-platform validation and required checks must pass before the candidate can be merged; Windows retention issue [#629](https://github.com/AndrewM-F/bun-native/issues/629) remains separate.
