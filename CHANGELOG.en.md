[简体中文](CHANGELOG.md) · **English**

# Changelog

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
