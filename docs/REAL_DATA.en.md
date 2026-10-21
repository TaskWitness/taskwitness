[简体中文](REAL_DATA.md) · **English**

# Testing on real data: REASSEMBLE

Snapshot 2026-10-21. Everything here is reproducible with
`examples/real_data/reassemble_grasp.py`. The data is **not** redistributed by this repository.

## Why this dataset, and what it cannot show

TaskWitness's main oracles read a load cell under the target or a button's own
contact switch. **No public robot dataset I found records either**, so the
place and button oracles cannot be tested on public data yet. What I searched:

- **FailBench's sources** (arXiv 2609.03611: 14 public sources, 2,197 attempts), RoboFail and UR5-Fail: video and labels, no external physical sensors.
- **ArmnetBench** (SO-101, per-episode success label), the LeRobot press-button datasets, RoboMIND: successes or policy rollouts, no force or contact sensing; RoboMIND removed failed runs.
- **RH20T**: has force/torque, not examined here.
- **REASSEMBLE** (Sliwowski et al., TU Wien 2025, CC-BY-4.0, [arXiv 2502.05086](https://arxiv.org/abs/2502.05086), [record](https://researchdata.tuwien.ac.at/records/0ewrv-8cb44), via the LeRobot v3 port [`robot-lev/reassemble`](https://huggingface.co/datasets/robot-lev/reassemble)):
  149 recordings of a Franka assembling and disassembling a NIST task board, 4,845
  action segments, each with a **human success label**, 30 fps gripper finger
  position and wrist force/torque. This is the closest match, so I used it.

It supports a **different, narrower test** than the place and button oracles: a
new `GraspOracle` that judges a pick from where the gripper's fingers stop. The
gripper width is the robot's own proprioception, so it is independent of the
policy's success claim and of vision, but **it is not an external sensor**. This
is a check of the principle (physical evidence beats trusting completion, with an
UNKNOWN band), not a validation of the load-cell oracle.

## Protocol

Fixed before looking at test results, using the dataset's official split
(111 train / 37 test episodes, disjoint):

1. Use only "Pick" segments (1,192; 8% failures overall).
2. For each object, learn the width band `[min, max]` from the final finger widths of **train** successes. Objects with fewer than 5 train successes would be skipped (no test pick was).
3. Judge every **test** pick (248: 224 successes, 24 failures) with the GraspOracle, a 1 mm UNKNOWN margin, and the default 0.5 mm "fingers stopped" threshold.
4. Compare with two baselines: *trust that the segment ended* (always PASS, what a system that does not check would say) and a *band-free* check, "gripper not fully open".

**Disclosure.** The first run showed that 56 of its 63 UNKNOWNs were "fingers
still moving at the end of the segment". I then added the repo's own conformal
calibration (fit on **train** successes only) for that threshold. I fixed
alpha = 0.1 before running it; alpha = 0.05 is a sensitivity run. Because I had
already seen the test breakdown, treat the calibrated rows as informed by it.

## Results (test split, 24 real failures)

| Judge | False passes (of 24 failures) | False fails (of 224 successes) | UNKNOWN | Accuracy when it decides |
| --- | --- | --- | --- | --- |
| Trust that the segment ended | 24/24 = 100% [86%, 100%] | 0% | 0% | 90.3% |
| Band-free: gripper not fully open | 21/24 = 87.5% [69%, 96%] | 0% | 0% | 91.5% |
| **GraspOracle**, fixed 0.5 mm stability | **2/24 = 8.3% [2.3%, 25.8%]** | 2/224 = 0.9% [0.2%, 3.2%] | 63/248 = 25.4% | 97.8% (181/185) |
| **GraspOracle**, conformal stability, alpha 0.1 (1.12 mm) | **2/24 = 8.3% [2.3%, 25.8%]** | 2/224 = 0.9% | 54/248 = 21.8% [17.1%, 27.3%] | 97.9% (190/194) |
| GraspOracle, conformal stability, alpha 0.05 (2.51 mm) | 3/24 = 12.5% [4.3%, 31.0%] | 2/224 = 0.9% | 36/248 = 14.5% | 97.6% (207/212) |

Intervals are 95% Wilson. The paired exact McNemar test against the band-free
check: 19 failures only the band-free check passes, none the other way, one-sided
p = 1.9e-6. The accuracy columns are not directly comparable: the GraspOracle
abstains on about a fifth of the picks and the baselines never do.

## What this shows, and what it does not

- **The principle holds on real data.** Of the 24 real failures, the calibrated GraspOracle failed 10 outright, left 12 UNKNOWN for review and passed 2 by mistake. Trusting completion passes all 24; the band-free check passes 21.
- **Only 24 failures.** The false-pass interval is wide (2.3% to 25.8%). The ordering against the baselines is clear; the exact rate is not.
- **The two misses are grasps of the wrong thing at the right width** (final widths 4.2 mm and 7.8 mm, both inside their bands). Finger position cannot see that.
- **The abstentions are mostly timing.** In the fixed-threshold run, 56 of 63 UNKNOWNs were "fingers still moving" because the annotated segment ends while the gripper is still settling (20% of successes). A real deployment would wait for the fingers to stop.
- **The conformal guarantee did not hold across sessions.** Calibrated for at most 10% of known-good windows to be called "moving", the test sessions had **16.5% (37/224)**; at alpha 0.05, **8.9% (20/224)** against 5%. Both are significant (about 3 standard errors). Train and test recordings differ session to session, which breaks the exchangeability the guarantee needs. Calibrate on recordings from several sessions and expect the realized rate to be higher than alpha.
- **Not shown:** anything about the load-cell or button oracles, or about vision judges; generalization to other robots, objects or labelers.

## Why the robot's own wrist sensor cannot replace a load cell

The same data gives real numbers for the wrist force/torque sensor (4,845 segment ends):

| | Measured | Compare |
| --- | --- | --- |
| Noise inside a half-second window (per-axis std) | median **11.6 g**-equivalent (P10 9.1 g, P90 29.4 g) | the `noisy` simulated rig uses 2 g |
| Spread of the settled Fz reading between segments | interquartile width **143 g**, P5 to P95 about 277 g (pose-dependent bias) | a 52 g block weighs 0.51 N |

A light object sits well below the pose-dependent offset. The simulation's
`wrist_ft` rig uses these numbers: TaskWitness returns UNKNOWN on every episode
(zero false passes, and no verdicts), which is the right behaviour for an unusable
sensor. See [SIMULATION.en.md](SIMULATION.en.md).

## Reproduce

The script reads the dataset through TaskWitness's own LeRobot adapter (`taskwitness lerobot`), which reproduces the numbers above exactly, so it doubles as a check of the adapter on a real 149-episode, 1.4 M-frame dataset.

```bash
pip install "taskwitness[lerobot]"
python examples/real_data/reassemble_grasp.py --download data/reassemble     # ~450 MB, no videos
python examples/real_data/reassemble_grasp.py --root data/reassemble                       # fixed stability threshold
python examples/real_data/reassemble_grasp.py --root data/reassemble --stability-alpha 0.1 # conformal, train only
```

Please cite the original authors if you use the data: Sliwowski, Jadav,
Stanovcic, Orbik, Heidersberger, Lee, *REASSEMBLE: A Multimodal Dataset for
Contact-rich Robotic Assembly and Disassembly*, TU Wien, 2025, DOI
10.48436/0ewrv-8cb44. The LeRobot port is by robot-lev; the data is CC-BY-4.0.
