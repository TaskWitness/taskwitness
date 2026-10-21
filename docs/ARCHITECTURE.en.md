[简体中文](ARCHITECTURE.md) · **English**

# Architecture

## Position in the stack

```
┌──────────────────────────────────────────────┐
│ Robot / VLA policy / agent                    │  controls the arm, records video,
│ (LeRobot, ROS 2, Inspect Robots, vendor)      │  may self-report success
└──────────────┬───────────────────────────────┘
               │ episode: task spec + sensor streams + video observations
┌──────────────▼───────────────────────────────┐
│ TaskWitness Core                              │
│  oracles ─► fusion ─► verdict + evidence      │
└──────────────┬───────────────────────────────┘
               │ PASS / FAIL / UNKNOWN + evidence bundle
┌──────────────▼───────────────────────────────┐
│ Evaluation harness, CI, statistics, humans    │
└──────────────────────────────────────────────┘
```

TaskWitness is deliberately independent of the policy under test: it never
receives policy internals, never sends commands, and ignores the policy's own
success claim when deciding.

## Data flow (v0.4)

```
raw logs ──calibrate──► calibration files
   │                         │
   ├── video ──track──► taskwitness.video/v0 ─┐
   │                                          ▼
   └────────────────────ingest──────────► taskwitness.episode/v0
                                              │
                                verify / batch│(PlaceOracle, ButtonPressOracle)
                                              ▼
                                  taskwitness.evidence/v0 ──sign──► signature
                                              │
                         evaluate / audit / estimate ──► statistics reports
```

## Modules

| Module | Responsibility |
| --- | --- |
| `core` | Verdicts, errors, strict episode validation (finite numbers, stream shapes), evidence-bundle assembly and integrity digests. |
| `oracle` | `PlaceOracle`: load-cell final state (`PLACED`, `ABSENT`, `PARTIAL_LOAD`, `OVERLOAD`, `UNSTABLE`, `NO_DATA`, `UNRESOLVABLE`), gripper state, video position; fusion rules. |
| `grasp` | `GraspOracle`: judge a pick from where the gripper's fingers stop, against the object's width band; UNKNOWN near the band edges or while the fingers move. Uses the robot's own gripper position, so it is independent of the policy's claim but not an external sensor. |
| `simulation` | Physics-based place and button episodes with known ground truth, adjustable noise, dropouts, tracker failures and clock offsets. Labels come from the latent story, never from an oracle. |
| `button` | `ButtonPressOracle`: contact runs with bounce merging and minimum hold, observation gaps, still-pressed and count limits; video can only veto. |
| `api` | `verify_episode` dispatches on `task.type`; `judge` returns a `Verdict`. |
| `config` | Oracle config files, validated strictly; their digest goes into reports. |
| `calibration` | Load-cell tare/scale fit with noise and residuals; camera homography (normalized DLT) with reprojection error. Pure Python. |
| `adapters` | `t_ms,value` logs and tracker output into episodes; strict parsing, clock alignment, provenance digests. |
| `vision` | Optional (`[vision]`): colour-blob tracker with region of interest; video reader assuming constant frame rate. |
| `evaluate` | Wilson intervals, exact McNemar, sequential paired comparison, absolute/conditional misses and audit coverage per stratum, external-judge audit (AUC, ECE, success bias), success-rate estimates. |
| `inference` | Anytime-valid sequential test (betting e-process), Waudby-Smith-Ramdas intervals, finite-sample prediction-powered inference, split-conformal bound. Pure Python; the guarantees are checked by simulation in the tests. |
| `thresholds` | Conformal calibration of the PlaceOracle thresholds from known-good recordings. |
| `signing` | Optional (`[sign]`): Ed25519 signatures over bundles, with explicit key pinning. |
| `integrations.inspect_robots` | `taskwitness` and `taskwitness_unknown` scorers for Inspect Robots, registered through entry points. |
| `cli` | All commands. |

The core (`core`, oracles, `api`, `config`, `calibration`, `adapters`,
`evaluate`, `inference`, `thresholds`) has no third-party dependencies.

## Design rules

1. **Physical evidence is authoritative.** Video may veto a PASS, never create one.
2. **UNKNOWN is a feature.** Missing, unsettled, unobserved or contradictory
   evidence yields UNKNOWN. The UNKNOWN rate is reported next to every accuracy number.
3. **Separation of evidence and labels.** Labels and robot claims are stripped
   before any oracle runs.
4. **Determinism.** Same input + same config + same version gives byte-identical
   bundles, so bundles can be diffed, cached and re-verified by third parties.
5. **No hidden thresholds.** The full config is embedded in every bundle; config
   files are digested into every report.
6. **Statistics before claims.** Rates come with intervals; comparisons between
   judges are paired tests on the same episodes.

## Not implemented yet

These are directions, not features.

- WitnessNode firmware and a live serial recorder (today: any logger that writes `t_ms,value`).
- A LeRobot dataset adapter (today: export per-episode scores and use `audit`).
- Learned or VLM-based video detectors (today: a colour-blob baseline).
- STEP's exact stopping rule, N-SCORE's partial-credit metrics and SureSim's paired real/simulation rectifier (today: a simpler sequential test for paired binary outcomes).

See [RESEARCH.en.md](RESEARCH.en.md) for the reasoning behind these choices.
