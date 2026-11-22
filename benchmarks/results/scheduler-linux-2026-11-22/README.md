# Idle-receive scheduler: Linux paired steady-update experiment

[Hosted run 45066375570](https://github.com/AndrewM-F/bun-native/actions/runs/45066375570) built baseline `492f2e0e9cc15cd2d95958e91dd579383b81ded1` and candidate `c4a502e68c8286857ad61a302094c2199a6001c3` on the same Ubuntu 24.04 x64 VM (4 vCPU Intel Xeon 6975P-C, Linux 7.0.0-1014-aws, Rust 1.98.1). The release host SHA-256 values were `7a307940e6fb0f805f4bc561ba949c9a259321ee9f87ae6da1887a3fcb38a3c0` and `7016865c7c15c82f8585604a7368a3a104748420dbf26ca7c89e5149f393e3e0`. The same Core AOT application, `b8dcda6d441785ef2ef7c3b0dd71b79628615951c08d1c1331a2b853d99b0fd2`, was used for every launch; the repository inspectors confirmed the compiled program and JIT-unused status. Its bundled module SHA-256 was `579906165a070525b6a6cc55a0c4e375d6807c8e1646daf2ebb123382bcfd742`.

In one isolated X11 session with software rendering, each process executed 1,000 sequential signal updates, 10 rotations and one mount with two rows. Four warmups preceded each cohort of 10 fresh-process AB/BA pairs. The repeat reversed starting order. The A/A control used the same baseline executable for both labels. All 72 launches passed the workload and cleanup assertions. The harness also checks the mode, Bun revision and exact workload. This measures public-core acknowledgement rather than visible input or display presentation.

Values are medians of per-process p95s and paired candidate-minus-baseline differences; 95% intervals use 10,000 bootstrap resamples of the 10 pairs with seed 20261122. These endpoints were selected after the earlier Mac experiment. Load and VM scheduling were uncontrolled, pairs may be correlated, and this is one hosted CPU model.

| Cohort                | p95 baseline / candidate | Paired p95 difference [95% interval] | 1,000-update total difference [95% interval] | p95 candidate faster |
| --------------------- | -----------------------: | -----------------------------------: | -------------------------------------------: | -------------------: |
| First                 |         1.060 / 0.088 ms |           -0.971 ms [-0.988, -0.969] |                      -78.0 ms [-87.8, -67.3] |                10/10 |
| Reversed-order repeat |         1.061 / 0.087 ms |           -0.973 ms [-0.990, -0.969] |                      -79.2 ms [-85.3, -70.8] |                10/10 |
| Identical-host A/A    |         1.065 / 1.062 ms |           -0.003 ms [-0.009, +0.001] |                        -4.1 ms [-10.5, +9.0] |                 7/10 |

The [retained original reports, process summaries, environment, compiler inspection and harness](raw.tar.gz) have SHA-256 `40cf316fef58ab6a0c110c7a069cf33b32221e1b2b995fbaf4f795213731616f`; the binaries are not included. The harness records the host and application hashes, load, every launch and its outcome. The diagnostic workflow itself was at `da61880d0b6510e3046f7ea72249b993ce65d5cd`.

The native scheduling step of [PR validation run 45065487692](https://github.com/AndrewM-F/bun-native/actions/runs/45065487692) separately passed in development and AOT, including real XTest input and paint progress during a saturated 128-command queue. That step is a fairness check, not a latency measurement. The validation run failed its independent dependency audit; the lockfile fix and exact final-head checks must pass before merge.
