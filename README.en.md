<div align="center">

# 🔍 TaskWitness

### Proof beyond perception.

**Don't trust the robot's claim. Verify what happened.**

[![CI](https://github.com/TaskWitness/taskwitness/actions/workflows/ci.yml/badge.svg)](https://github.com/TaskWitness/taskwitness/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](pyproject.toml)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)
![Core dependencies: none](https://img.shields.io/badge/core%20dependencies-none-brightgreen.svg)

[简体中文](README.md) · **English**

[Quickstart](#-3-minute-quickstart) · [How it works](#️-how-it-works) · [Toolchain](#️-from-a-real-rig-to-an-honest-result) · [Research](#-research-basis) · [Roadmap](#️-roadmap)

<img src="docs/assets/demo.en.svg" alt="Synthetic episode: video says the block is in the zone (PASS), the load cell shows the plate is empty (FAIL)" width="860">

<sub>Synthetic episode <code>03_bounced_off</code>, rendered from <code>examples/synthetic</code>. Not a real-robot measurement.</sub>

</div>

---

## 💡 Why TaskWitness?

Robot policies, VLAs and vision-based success detectors increasingly say *"task complete"*. But a camera can be fooled: the gripper still holds the block, the block bounced off, the tool only hovers over the button. Recent work agrees: on FailBench the best VLM judge reaches only 0.77 mean balanced accuracy and is systematically biased toward "success" when evidence is ambiguous ([research notes](docs/RESEARCH.en.md)).

**TaskWitness is an independent, sensor-grounded verification layer for Physical AI.** It sits *outside* the robot policy, weighs physical sensor evidence first and video second, returns a verdict you can audit, and ships the statistics needed to check other judges against it.

| | Vision-only judge | **TaskWitness** |
| --- | --- | --- |
| Primary evidence | Pixels | **Physical sensors** |
| Trusts the robot's self-report? | Often | **Never** |
| When evidence is missing | Guesses | **Says `UNKNOWN`** |
| Output | A score | **Verdict + evidence bundle** |
| Reproducible & tamper-evident | Rarely | **Yes (SHA-256, optional signatures)** |

> TaskWitness does **not** control robots, train policies, or replace LeRobot, ROS 2, Inspect Robots or other evaluation frameworks. It plugs into them as an external result judge.

---

## 🚀 3-minute quickstart

No robot. No GPU. The core has no dependencies beyond Python 3.10+.

```bash
git clone https://github.com/TaskWitness/taskwitness
cd taskwitness
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

taskwitness batch examples/synthetic --out report.json
taskwitness batch examples/synthetic_button --out report-button.json
```

```text
PASS     01_clean_success.json  (stable load on the target plate matches the object's mass)
FAIL     02_not_released.json  (only part of the object's weight is on the plate while the gripper is still closed: object not released)
FAIL     03_bounced_off.json  (load cell shows the target plate is empty at end of episode)
UNKNOWN  04_sensor_dropout.json  (no usable load-cell evidence; refusing to judge from video alone)
UNKNOWN  05_evidence_conflict.json  (load matches the object but video places it outside the zone; evidence conflict)
5 episodes: 1 PASS, 2 FAIL, 2 UNKNOWN; 0/5 labeled episodes disagree with their label
```

| Episode | Scenario | Vision-only | TaskWitness |
| --- | --- | --- | --- |
| 01 | Block placed and released cleanly | PASS | **PASS** |
| 02 | Block touches the plate but the gripper never opens | PASS | **FAIL** |
| 03 | Block bounces off behind a fixture; the video tracker stays locked on the zone | PASS | **FAIL** |
| 04 | Load-cell stream drops before the placement | PASS | **UNKNOWN** |
| 05 | Weight is right, but the camera sees the block outside the zone | FAIL | **UNKNOWN** |
| b01 | Button pressed for 200 ms, with contact bounce | PASS | **PASS** |
| b02 | Tool hovers over the button without pushing it | PASS | **FAIL** |
| b03 | Tool brushes the button: 30 ms of contact | PASS | **FAIL** |
| b04 | Button still held down when recording stops | PASS | **UNKNOWN** |
| b05 | Switch stream drops before the tool arrives | PASS | **UNKNOWN** |
| b06 | Switch fires while the tool is across the table | FAIL | **UNKNOWN** |

👉 In 02, 03, b02 and b03, a video-only judge says **PASS**. Physical evidence says **FAIL**.

**Honest statistics:** with only 4 discordant pairs, the exact McNemar test gives p = 0.0625, which is not significant, and the tool says so instead of overclaiming:

```bash
taskwitness evaluate examples/synthetic examples/synthetic_button
```

Verify one episode and check its evidence bundle:

```bash
taskwitness verify examples/synthetic/02_not_released.json --out bundle.json
taskwitness check bundle.json --episode examples/synthetic/02_not_released.json
```

`verify` exits `0` for PASS, `1` for FAIL, `2` for UNKNOWN and `3` for bad input, so it can gate a CI pipeline or an evaluation loop.

---

## ⚙️ How it works

```text
 robot / VLA / agent ──► actions · video · self-reported "success"
                                   │
                          TaskWitness Core
       ┌────────────────┬──────────┴───────┬─────────────────┐
 load cell / button   gripper state     video oracle     (more oracles later)
       └────────────────┴────────┬─────────┴─────────────────┘
                          Evidence fusion
                                 │
            PASS / FAIL / UNKNOWN  +  evidence bundle
     timeline · measurements · reasons · config · SHA-256 digests
```

**Three rules**

1. 🏋️ **Physics first.** The load cell or the button's own contact is authoritative. Video can veto a PASS, never create one.
2. ❓ **`UNKNOWN` is a feature.** Missing, unsettled, unobserved or conflicting evidence yields `UNKNOWN` instead of a guess.
3. 🙈 **Blind to claims and labels.** The robot's self-report and ground-truth labels are stripped before judging, and used only afterwards for comparison.

<details>
<summary><b>Full PlaceOracle decision table</b></summary>

| Load cell (final settle window) | Gripper | Video | Verdict |
| --- | --- | --- | --- |
| object too light to tell from an empty plate | any | any | UNKNOWN |
| no / too few samples | any | any | UNKNOWN |
| not settled | any | any | UNKNOWN |
| heavier than the object | any | any | UNKNOWN |
| empty | any | any | **FAIL** |
| partial weight | closed | any | **FAIL** (not released) |
| partial weight | open / unknown | any | UNKNOWN |
| matches object | any | out of zone | UNKNOWN (conflict) |
| matches object | closed | in zone / unavailable | UNKNOWN (may be pressing) |
| matches object | open / unknown | in zone / unavailable | **PASS** |

</details>

<details>
<summary><b>Full ButtonPressOracle decision table</b></summary>

| Button contact | Video | Verdict |
| --- | --- | --- |
| no data | any | UNKNOWN |
| still pressed at the end | any | UNKNOWN (press not completed) |
| too few presses and the stream has gaps | any | UNKNOWN (may have been missed) |
| more than `max_presses` | any | **FAIL** |
| no or too few presses, fully observed | any | **FAIL** (hover or too little force) |
| required complete presses | tool never at the button | UNKNOWN (something else may have pressed it) |
| required complete presses | tool at the button / unavailable | **PASS** |

Contact bounce is merged; contacts shorter than `min_hold_s` do not count as presses.

</details>

All thresholds live in the config and are recorded in every bundle. 📄 Formats: [docs/EVIDENCE_SPEC.en.md](docs/EVIDENCE_SPEC.en.md) · 🏗️ Design: [docs/ARCHITECTURE.en.md](docs/ARCHITECTURE.en.md)

---

## 🛠️ From a real rig to an honest result

```
record logs ─► calibrate ─► track ─► ingest ─► verify / evaluate / audit / estimate ─► sign
```

| Command | What it does |
| --- | --- |
| `calibrate load-cell` / `calibrate camera` | Load-cell tare and scale (reports noise and residuals); pixel-to-plate homography (reports reprojection error) |
| `track` | Track a coloured object or marker in video, with a region of interest (needs `[vision]`) |
| `ingest place` / `ingest button_press` | Turn `t_ms,value` logs and tracker output into an episode, recording the SHA-256 of every source file |
| `verify` / `batch` / `check` | Judge, judge a directory, check bundle integrity; all accept `--config` to freeze thresholds |
| `evaluate` | Against human labels: conditional and absolute misses, false fails, UNKNOWN rate (with Wilson intervals), audit coverage, per-failure-mode strata, exact McNemar test |
| `audit` | Audit an external judge (Robometer, TOPReward, a VLM, an operator) on the same episodes: balanced accuracy, ROC-AUC, calibration error, success bias |
| `estimate` | Prediction-powered inference: verdicts on every episode + labels on a random subset give a success rate with a valid interval |
| `keygen` / `sign` / `verify-signature` | Ed25519 signatures for bundles (needs `[sign]`) |

The full protocol is in the [experiment guide](docs/EXPERIMENT_GUIDE.en.md).

```bash
pip install -e '.[vision]'    # video tracking: numpy + OpenCV
pip install -e '.[sign]'      # signatures: cryptography
pip install -e '.[inspect]'   # Inspect Robots integration
pip install -e '.[all]'
```

### 🔌 Integration: Inspect Robots

Installing TaskWitness registers two scorers with [Inspect Robots](https://github.com/robocurve/inspect-robots) through entry points, tested inside a real `inspect_robots.eval()` loop:

```python
Task(name="place_cube", scenes=[Scene(id="s1", instruction="put the cube on the plate",
     target=Target(kind="taskwitness.place", spec={"object": {"mass_g": 52.0}, "target_zone": {...}}))],
     scorer=["success_at_end", "taskwitness", "taskwitness_unknown"], max_steps=200)
```

The embodiment only needs to report `load_cell_g` (and optionally `gripper` / `button_pressed`) in `Observation.state` and set `state_time`. Inspect Robots averages scores, so run both scorers to keep the UNKNOWN rate next to the pass rate.

---

## 📚 Research basis

TaskWitness's design follows recent work: FailBench (success bias of VLM judges), coverage shift (better policies leave failures that are harder to see), No Free Checker (verifier credibility falls as availability rises), LeRobot v0.6 reward models (Robometer, TOPReward), and STEP / N-SCORE / SureSim / PPI (statistics for few real trials). See [docs/RESEARCH.en.md](docs/RESEARCH.en.md).

---

## 📦 What's in v0.2

**Honest status: pre-alpha.** Every example in this repo is synthetic; no result here is yet a measurement from a real robot, camera or load cell.

| ✅ Available now | 🛠️ Not built yet |
| --- | --- |
| `PlaceOracle`, `ButtonPressOracle` | WitnessNode firmware and a live serial recorder |
| Strict episode validation (rejects NaN/inf, points at the bad field) | LeRobot dataset adapter |
| Load-cell and camera calibration, log ingestion, colour-blob video tracking | Learned or VLM-based video detectors |
| `evaluate` / `audit` / `estimate` statistics | Anytime-valid sequential tests, finite-sample PPI bounds |
| Inspect Robots scorers (tested in a real eval loop) | Results on real hardware |
| Deterministic, tamper-evident bundles with optional signatures | |
| 11 synthetic episodes, 116 tests, CI | |

---

## 🗺️ Roadmap

| Phase | Focus | Done when |
| --- | --- | --- |
| **D1–7** | Synthetic demo, CLI, tests ✅; public videos with human labels | A stranger runs it unaided; 5+ target developers give feedback |
| **D8–30** | Phone camera + load cell, 200+ independently labeled trials (toolchain ready ✅) | Does fusion cut false passes under pre-registered conditions? |
| **D31–60** | WitnessNode sensor box, framework plugin (Inspect Robots ✅), community robots (e.g. SO-101) | 2+ external real-robot setups run it |
| **D61–90** | Publish real-data results, first WitnessBench release | 1+ independent external reproduction |

Details: [docs/ROADMAP_90_DAYS.en.md](docs/ROADMAP_90_DAYS.en.md) · Hardware notes: [hardware/README.en.md](hardware/README.en.md) · Changes: [CHANGELOG.en.md](CHANGELOG.en.md)

---

## 🧩 Project family

| Name | What | Status |
| --- | --- | --- |
| **TaskWitness Core** | Open-source verification SDK | v0.2 (this repo) |
| **WitnessNode** | Low-cost sensor box | design notes |
| **WitnessKit** | Physical experiment kit | planned |
| **WitnessBench** | Community test dataset | planned |

**Open source, for real:** Apache-2.0. Oracles, sensor guides, fusion logic, statistics, evidence export and `UNKNOWN` handling are and will stay open.

---

## 🤝 Contributing

The most valuable contribution right now is **a real experiment**: labeled place attempts with load-cell data, collected with the [experiment guide](docs/EXPERIMENT_GUIDE.en.md), *especially* cases where TaskWitness gets it wrong.

Have a robot arm, a load cell, or just a phone and a kitchen scale? Open an issue. See [CONTRIBUTING.en.md](CONTRIBUTING.en.md).

---

<div align="center">

**When AI says success, who checks reality?**

<sub>Licensed under <a href="LICENSE">Apache-2.0</a>.</sub>

</div>
