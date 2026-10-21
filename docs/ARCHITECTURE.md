# Architecture

## Position in the stack

```
┌──────────────────────────────────────────────┐
│ Robot / VLA policy / agent                    │  controls the arm, records video,
│ (LeRobot, ROS 2, vendor stacks)               │  may self-report success
└──────────────┬───────────────────────────────┘
               │ episode: task spec + sensor streams + video observations
┌──────────────▼───────────────────────────────┐
│ TaskWitness Core                              │
│  oracles ─► fusion ─► verdict + evidence      │
└──────────────┬───────────────────────────────┘
               │ PASS / FAIL / UNKNOWN + evidence bundle
┌──────────────▼───────────────────────────────┐
│ Evaluation harness, CI, dashboards, humans    │
└──────────────────────────────────────────────┘
```

TaskWitness is deliberately independent of the policy under test: it never
receives policy internals, never sends commands, and ignores the policy's own
success claim when deciding.

## Components (v0.1)

| Module | Responsibility |
| --- | --- |
| `oracle.validate_episode` | Reject malformed episodes before judging. |
| `oracle.sensor_oracle` | Classify the final settle window of the load cell: `PLACED`, `ABSENT`, `PARTIAL_LOAD`, `OVERLOAD`, `UNSTABLE`, `NO_DATA`. |
| `oracle.gripper_oracle` | Final gripper state: `OPEN`, `CLOSED`, `NO_DATA`. |
| `oracle.video_oracle` | Classify confident end-of-episode object positions: `IN_ZONE`, `OUT_OF_ZONE`, `LOW_CONFIDENCE`, `NO_DATA`. |
| `oracle.fuse` | Rule table that turns oracle states into a verdict with human-readable reasons. |
| `oracle.verify_place` | Run everything and assemble the evidence bundle. |
| `oracle.verify_bundle_integrity` | Recompute digests to detect edited bundles or mismatched inputs. |
| `cli` | `verify`, `batch`, `check`. |

## Design rules

1. **Physical evidence is authoritative.** Video may veto a PASS, never create one.
2. **UNKNOWN is a feature.** Missing, unsettled or contradictory evidence yields
   UNKNOWN. The UNKNOWN rate is a metric to report alongside accuracy, not to hide.
3. **Separation of evidence and labels.** Labels and robot claims are stripped
   before any oracle runs.
4. **Determinism.** Same input + same config + same version gives byte-identical
   bundles, so bundles can be diffed, cached and re-verified by third parties.
5. **No hidden thresholds.** The full config is embedded in every bundle.

## Planned extension points (not implemented)

These are directions, not features. Do not document them as available until they ship.

- **Sensor adapters**: read HX711 load-cell streams, gripper telemetry, timestamps.
- **Video inference**: produce `object_xy` + confidence from raw frames instead of
  requiring pre-computed positions.
- **Calibration**: map camera coordinates to the plate frame; tare and scale the load cell.
- **More oracles**: `ButtonPressOracle` (v0.2), then others driven by real demand.
- **Framework plugins**: expose TaskWitness as a success detector / evaluator inside
  existing robot-learning evaluation loops.
