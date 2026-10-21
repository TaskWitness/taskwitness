[简体中文](CHANGELOG.md) · **English**

# Changelog

## 0.5.0 (2026-10-21)

### Added

- **LeRobot v3 dataset adapter**: `taskwitness lerobot ROOT --mapping map.json --out DIR` (optional `[lerobot]` = pyarrow). It reads the dataset's parquet files directly, needs no `lerobot` package and does not read the videos. It maps chosen columns to load-cell, gripper-width, button and gripper streams, can split a long recording into one episode per action by a column, reads the human label, filters by a task-text prefix, and records the SHA-256 of the data files. `LeRobotDataset.video_span` gives each episode's slice of the concatenated camera videos.
- `taskwitness track --start-s --end-s` and `read_video(start_s, end_s)`: track one slice of a concatenated video.
- A worked mapping, `examples/lerobot/reassemble_pick_mapping.json`.

### Verified

- Run on the LeRobot port of REASSEMBLE (149 episodes, 1.4 M frames): 1,192 pick segments, 1,092 successes and 100 failures, identical to the earlier stand-alone script. `examples/real_data/reassemble_grasp.py` now reads through the adapter and gives the same results item for item (2 false passes among the 24 test failures).
- Tests use a small LeRobot v3 dataset built by hand to the real layout (two data files, episodes with several segments), covering mapping validation, the version check, a missing data file and a non-contiguous episode.

### Limits

- One LeRobot episode must lie within one data file (true of files written by LeRobot's own tools); only v3 is supported; results are not written back into the dataset.

## 0.4.0 (2026-10-21)

TaskWitness is now tested against a physics simulation and a real public dataset, and the oracles were fixed where those tests found problems.

### Added

- **Simulation**: `taskwitness simulate place|button_press` and `examples/simulation/study.py`. Episodes are generated from a latent physical story (load-cell noise and drift, ringing after landing, dropped samples, frozen trackers, clock offsets, contact bounce) and labelled from that story, never from an oracle; the mix deliberately includes failures the oracles were not designed for (for example another object on the plate with a frozen tracker). Results: [docs/SIMULATION.en.md](docs/SIMULATION.en.md).
- **GraspOracle** (task type `grasp`): judge a pick from where the gripper's fingers stop, against the object's width band.
- **Real-data test**: `examples/real_data/reassemble_grasp.py` tests the GraspOracle on REASSEMBLE (CC-BY-4.0, Franka, human success labels) with the official train/test split. On the test split's 24 real failures it falsely passes 2 (8.3%, interval 2.3%-25.8%), against 100% for "trust that the segment ended" and 87.5% for a band-free "gripper not fully open" check. It also records, honestly, that the conformal guarantee did not hold across sessions. See [docs/REAL_DATA.en.md](docs/REAL_DATA.en.md).
- `wrist_ft` simulated rig: the measured noise (median 11.6 g) and bias (interquartile width 143 g) of the real wrist force sensor show why the robot's own wrist sensor cannot replace a load cell.

### Changed (driven by what simulation and real data found)

- **PlaceOracle** now requires the plate to read empty at the start (`baseline_window_s`, the median of the first 0.5 s): a leftover object or bad tare gets UNKNOWN instead of being counted as this trial's success. In simulation (lab rig) false passes fall from 5.5% to 3.3% at no cost on ordinary successes.
- **ButtonPressOracle**: sampling only brackets a contact's duration. It used to estimate duration from sample spacing, which counted 37 of 111 light brushes as presses at a 20 Hz switch rate; now only a contact guaranteed at least `min_hold_s` counts, and an unresolvable one is UNKNOWN (`UNRESOLVED_HOLD`). Also, with a cap on presses and one contact that cannot be ruled out as a press, it no longer says PASS (that hole let 1.0% of real failures pass at 20 Hz; now 0).
- The trade-off between `calibrate thresholds` and the defaults is quantified: at load noise of 2 g and up, conformal calibration cuts UNKNOWN on ordinary successes from 44% (100% at 4 g) to 14% (20%); at 1 g and below the calibrated thresholds are stricter and UNKNOWN rises from about 2% to 6-11%.

### Notes

- The simulator's failure modes and noise levels are the author's assumptions, not measurements.
- No public robot dataset records a load cell or a button contact, so the place and button oracles still have no real-hardware result.

## 0.3.0 (2026-10-21)

Fills in the statistical methods v0.2 listed as not built. Every statistical guarantee is checked by simulation, and limits found in testing are documented.

### Added

- **Sequential test**: `taskwitness evaluate` gains an anytime-valid paired comparison (betting e-process). Look whenever you like and stop whenever you like; the type-I error stays at most alpha. `--order-by TAG` sets the episode order and `--alpha` the level. In simulation: under no difference it rejects 3.2% of 1,500 runs (limit 5%); a true 85/15 difference is always detected, at a median of 10 discordant pairs.
- **Finite-sample intervals**: `taskwitness estimate` gains Waudby-Smith-Ramdas betting intervals (labels only) and finite-sample prediction-powered inference (a union bound of two betting intervals).
- **Conformal threshold calibration**: `taskwitness calibrate thresholds` sets the stability, empty and mass-tolerance thresholds from known-good recordings so that a new good window exceeds a threshold with probability at most alpha. It errors rather than guesses when there is too little data, and flags objects too light to tell from empty.
- New modules `inference` and `thresholds`: pure Python, no new dependencies.

### Notes

- The finite-sample prediction-powered interval is not always narrower: with a judge that falsely passes 10% of failures, 400 episodes and 40 labels it is wider than labels alone (0.68 vs 0.44); it only wins with an accurate judge and thousands of episodes. `estimate` prints every interval and reminds you to choose beforehand which one to report.
- The sequential test is simpler than STEP and N-SCORE and covers paired binary outcomes only.

## 0.2.0 (2026-10-21)

The new features follow recent research; the reasoning is in [docs/RESEARCH.en.md](docs/RESEARCH.en.md).

### Added

- **ButtonPressOracle**: the button's own contact is the primary evidence; contact bounce is merged, a minimum hold is required, observation gaps and a press still held at the end are detected, press counts can be bounded; video can only veto. Six synthetic episodes in `examples/synthetic_button`.
- **Calibration**: `taskwitness calibrate load-cell` (tare, scale, noise, residuals, suggested thresholds) and `taskwitness calibrate camera` (normalized-DLT homography, reprojection error, degenerate-point detection).
- **Ingestion**: `taskwitness ingest place|button_press` turns `t_ms,value` logs and tracker output into episodes on one clock and records the SHA-256 of every source file.
- **Video tracking** (optional `[vision]`): `taskwitness track`, a colour-blob baseline with a region of interest.
- **Statistics**:
  - `taskwitness evaluate`: conditional and absolute misses, false fails, UNKNOWN rate (Wilson intervals), audit coverage, per-tag strata, exact McNemar test;
  - `taskwitness audit`: audit an external judge (balanced accuracy, ROC-AUC, ECE, success bias) with a paired comparison against TaskWitness;
  - `taskwitness estimate`: prediction-powered success-rate estimate.
- **Config files**: `--config` freezes thresholds; reports record `config_sha256`.
- **Signatures** (optional `[sign]`): `keygen`, `sign`, `verify-signature`, Ed25519 with explicit key pinning.
- **Inspect Robots integration** (optional `[inspect]`): `taskwitness` and `taskwitness_unknown` scorers registered through entry points and tested in a real `inspect_robots.eval()` loop.
- Python API: `taskwitness.judge()`, `taskwitness.verify_episode()`.
- Docs: research notes, experiment guide; every document in Chinese and English.

### Changed

- Stricter episode validation: NaN and infinity are rejected (Python's JSON parser accepts them), and errors name the field, e.g. `sensors.load_cell[3]`.
- PlaceOracle: an object too light to tell from an empty plate yields `UNRESOLVABLE` → UNKNOWN instead of a wrong verdict.
- `batch` continues past a bad file and lists errors in the report (exit code 3).
- CI runs a core-only job to keep the core dependency-free.

## 0.1.0 (2026-10-21)

- First release: PlaceOracle, evidence fusion, deterministic bundles, `verify` / `batch` / `check`, five synthetic episodes.
