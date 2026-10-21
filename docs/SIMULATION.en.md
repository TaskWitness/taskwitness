[简体中文](SIMULATION.md) · **English**

# Simulation study

Everything on this page is **synthetic**. It shows how TaskWitness behaves under
the simulator's assumptions, with known ground truth, as the rig gets worse. It
is not a measurement of any real rig. Regenerate it with
`python examples/simulation/study.py` (about 15 minutes at the default size).

## How it works, and how it avoids grading its own homework

- Each episode is generated from a **latent physical story**: the object was released and rests on the plate, bounced out, was held by the gripper, was the wrong object, was something left on the plate, and so on. Load-cell, gripper, switch and video streams are produced from that story with realistic imperfections: noise, drift, spikes, ringing after landing, dropped samples, zero-point offsets, contact bounce, a video tracker that freezes on its last position, occlusion and a clock offset between video and sensors.
- The **label comes from the story, never from an oracle**, and is binary (PASS or FAIL) as real human labels are. UNKNOWN is only ever the verifier's answer.
- The mix deliberately includes failures the oracles were **not** designed to catch: a foreign object of the right weight landing on the plate mid-trial while the tracker is frozen, so both channels are fooled. The reported false-pass rate is therefore not trivially zero.
- The **vision-only baseline is a position check** (is the tracked object inside the target zone at the end?), not a learned judge. FailBench reports the best real VLM judges at about 0.77 balanced accuracy, so a real baseline would sit somewhere other than this one. Treat the vision-only columns as "what the video evidence alone supports", not as a model of any particular system.
- **Reading the UNKNOWN columns.** "All" includes deliberately ambiguous cases (dropouts, objects resting on the edge, a gripper pressing on the plate, the wrong object), which is why it is large. "Ordinary successes" is only the plain successful placements, and shows what the rig costs a normal trial.
- 1,500 episodes per cell, seed 1; intervals are 95% Wilson. False passes are measured among real failures; false fails among real successes.


## Place: rig quality and the plate-empty-at-start check

| rig | baseline check | TaskWitness false passes (of real failures) | vision-only false passes | TaskWitness false fails | TaskWitness UNKNOWN (all) | TaskWitness UNKNOWN (of ordinary successes) |
|---|---|---|---|---|---|---|
| clean | on | 2.2% [1.4%, 3.5%] | 51.1% [47.5%, 54.7%] | 0.0% [0.0%, 0.5%] | 31.0% [28.7%, 33.4%] | 0.0% [0.0%, 0.6%] |
| clean | off | 3.2% [2.1%, 4.7%] | 51.1% [47.5%, 54.7%] | 0.0% [0.0%, 0.5%] | 30.5% [28.3%, 32.9%] | 0.0% [0.0%, 0.6%] |
| lab | on | 3.3% [2.2%, 4.8%] | 53.8% [50.2%, 57.4%] | 0.0% [0.0%, 0.5%] | 32.6% [30.3%, 35.0%] | 2.4% [1.5%, 3.9%] |
| lab | off | 5.5% [4.0%, 7.4%] | 53.8% [50.2%, 57.4%] | 0.0% [0.0%, 0.5%] | 31.5% [29.2%, 33.9%] | 2.4% [1.5%, 3.9%] |
| noisy | on | 3.0% [2.0%, 4.5%] | 48.6% [45.0%, 52.3%] | 0.0% [0.0%, 0.5%] | 58.8% [56.3%, 61.3%] | 43.4% [39.6%, 47.3%] |
| noisy | off | 4.4% [3.1%, 6.1%] | 48.6% [45.0%, 52.3%] | 0.0% [0.0%, 0.5%] | 58.0% [55.5%, 60.5%] | 43.1% [39.2%, 47.0%] |

The plate-empty-at-start check removes about two points of false passes on a lab rig (5.5% to 3.3%) at no cost on ordinary successes. The default thresholds are fine up to about 1 g of noise; at 2 g they make 43% of ordinary successes UNKNOWN on the `noisy` rig (see the calibration table).


## Place, lab rig: verdicts by what really happened

| latent mode | truth | episodes | TaskWitness PASS / FAIL / UNKNOWN | vision-only PASS / FAIL / UNKNOWN |
|---|---|---|---|---|
| bounce_out | FAIL | 114 | 0 / 108 / 6 | 0 / 102 / 12 |
| dropout_fail | FAIL | 50 | 0 / 0 / 50 | 0 / 44 / 6 |
| dropout_success | PASS | 54 | 0 / 0 / 54 | 46 / 0 / 8 |
| edge | FAIL | 95 | 0 / 0 / 95 | 31 / 30 / 34 |
| foreign_object | FAIL | 40 | 24 / 0 / 16 | 18 / 16 / 6 |
| late_placement | PASS | 39 | 0 / 0 / 39 | 37 / 0 / 2 |
| leftover_object | FAIL | 24 | 0 / 0 / 24 | 14 / 8 / 2 |
| miss | FAIL | 122 | 0 / 114 / 8 | 71 / 42 / 9 |
| not_released | FAIL | 138 | 0 / 135 / 3 | 130 / 0 / 8 |
| pressing | FAIL | 73 | 0 / 0 / 73 | 64 / 0 / 9 |
| slow_settle | PASS | 50 | 18 / 0 / 32 | 47 / 0 / 3 |
| success | PASS | 627 | 612 / 0 / 15 | 570 / 0 / 57 |
| wrong_object | FAIL | 74 | 0 / 0 / 74 | 65 / 0 / 9 |

Where each verdict comes from, lab rig. Vision-only passes anything that looks in-zone: objects still held by the gripper, pressed on the plate, the wrong object, or left on the plate. TaskWitness fails what physics contradicts (an empty plate after a bounce or miss, a partly loaded plate under a closed gripper) and abstains on what it cannot resolve (edge cases, pressing, wrong object, dropouts). Its false passes come almost entirely from `foreign_object`: 24 of 40 such trials pass, because a plate weight matching the object and a frozen tracker fool both channels. `leftover_object` is now caught by the empty-at-start check, and the oracle never says FAIL for a wrong object, it says UNKNOWN.


## Place: load-cell noise, default thresholds vs conformal calibration

| noise sd (g) | thresholds | stability / empty / tolerance (g) | false passes | UNKNOWN of ordinary successes | false fails |
|---|---|---|---|---|---|
| 0.1 | default | 2.00 / 3.00 / 3.00 | 3.3% [2.2%, 4.8%] | 2.2% [1.3%, 3.7%] | 0.0% [0.0%, 0.5%] |
| 0.1 | calibrated | 0.13 / 0.43 / 0.40 | 3.3% [2.2%, 4.8%] | 5.9% [4.3%, 8.0%] | 0.0% [0.0%, 0.5%] |
| 0.4 | default | 2.00 / 3.00 / 3.00 | 3.3% [2.2%, 4.8%] | 2.4% [1.5%, 3.9%] | 0.0% [0.0%, 0.5%] |
| 0.4 | calibrated | 0.52 / 0.48 / 0.47 | 3.2% [2.1%, 4.7%] | 6.2% [4.6%, 8.4%] | 0.0% [0.0%, 0.5%] |
| 1.0 | default | 2.00 / 3.00 / 3.00 | 3.3% [2.2%, 4.8%] | 2.6% [1.6%, 4.1%] | 0.0% [0.0%, 0.5%] |
| 1.0 | calibrated | 1.29 / 0.61 / 0.69 | 2.7% [1.8%, 4.2%] | 10.8% [8.6%, 13.5%] | 0.0% [0.0%, 0.5%] |
| 2.0 | default | 2.00 / 3.00 / 3.00 | 1.8% [1.0%, 3.0%] | 43.7% [39.9%, 47.6%] | 0.0% [0.0%, 0.5%] |
| 2.0 | calibrated | 2.54 / 1.04 / 1.11 | 2.7% [1.8%, 4.2%] | 13.9% [11.4%, 16.8%] | 0.0% [0.0%, 0.5%] |
| 4.0 | default | 2.00 / 3.00 / 3.00 | 0.0% [0.0%, 0.5%] | 100.0% [99.4%, 100.0%] | 0.0% [0.0%, 0.5%] |
| 4.0 | calibrated | 4.81 / 1.80 / 1.79 | 2.3% [1.5%, 3.7%] | 19.8% [16.8%, 23.1%] | 0.0% [0.0%, 0.5%] |

Default thresholds are good up to 1 g of noise (2% of ordinary successes UNKNOWN), poor at 2 g (44%) and unusable at 4 g (100%, which is also why their false-pass rate there is 0%: they never decide). Conformal calibration (`calibrate thresholds`, alpha 0.05, 120 s of known-good recording per state) brings 2 g and 4 g down to 14% and 20% at the price of 2.3% to 2.7% false passes. At 1 g and below, calibration is **worse** on ordinary successes (6% to 11% against 2% to 3%), because it sets three tight thresholds at alpha 0.05 each. On real data the conformal guarantee also did not hold across sessions ([REAL_DATA.en.md](REAL_DATA.en.md)).


## Place: a dedicated load cell vs the robot's own wrist force sensor (52 g block; wrist noise 11.6 g, offset sd 106 g, measured on REASSEMBLE)

| sensor | TaskWitness false passes | false fails | UNKNOWN (all) | UNKNOWN (ordinary successes) | vision-only false passes |
|---|---|---|---|---|---|
| lab | 3.3% [2.2%, 4.8%] | 0.0% [0.0%, 0.5%] | 32.6% [30.3%, 35.0%] | 2.4% [1.5%, 3.9%] | 53.8% [50.2%, 57.4%] |
| wrist_ft | 0.0% [0.0%, 0.5%] | 0.0% [0.0%, 0.5%] | 100.0% [99.7%, 100.0%] | 100.0% [99.4%, 100.0%] | 55.1% [51.4%, 58.6%] |

The robot's own wrist force sensor, with the noise (11.6 g) and between-pose offset (sd 106 g) measured on REASSEMBLE, cannot verify a 52 g block: TaskWitness returns UNKNOWN on every episode. That is the right behaviour (no false passes, and no pretence of a verdict). The vision-only judge is unaffected, and just as wrong.


## Place: how often the video tracker freezes on a stale position

| stale tracker prob | vision-only false passes | TaskWitness false passes |
|---|---|---|
| 0.0 | 39.7% [36.2%, 43.3%] | 0.8% [0.4%, 1.8%] |
| 0.3 | 46.4% [42.8%, 50.1%] | 1.9% [1.1%, 3.2%] |
| 0.6 | 53.8% [50.2%, 57.4%] | 3.3% [2.2%, 4.8%] |
| 0.9 | 60.5% [57.0%, 64.0%] | 4.9% [3.6%, 6.8%] |

TaskWitness's false passes track how often the tracker freezes, because only the foreign-object mode can fool both channels. Vision-only is high even with a perfect tracker (40%): an object still held by the gripper, or the wrong object, is in the zone.


## Place: load-cell sample rate and dropped samples

| load Hz | min_settle_samples | dropped samples | false passes | UNKNOWN of ordinary successes | UNKNOWN (all) |
|---|---|---|---|---|---|
| 5.0 | 5 | 0.0 | 3.4% [2.3%, 5.0%] | 5.7% [4.2%, 7.8%] | 34.5% [32.1%, 36.9%] |
| 5.0 | 5 | 0.05 | 2.6% [1.7%, 4.0%] | 25.4% [22.1%, 28.9%] | 48.5% [45.9%, 51.0%] |
| 5.0 | 5 | 0.2 | 1.5% [0.8%, 2.7%] | 64.3% [60.4%, 67.9%] | 76.1% [73.8%, 78.2%] |
| 5.0 | 5 | 0.4 | 0.4% [0.1%, 1.2%] | 91.4% [88.9%, 93.3%] | 94.3% [93.0%, 95.4%] |
| 5.0 | 2 | 0.0 | 3.7% [2.6%, 5.3%] | 0.6% [0.2%, 1.6%] | 30.4% [28.1%, 32.8%] |
| 5.0 | 2 | 0.05 | 3.4% [2.3%, 5.0%] | 0.8% [0.3%, 1.9%] | 30.6% [28.3%, 33.0%] |
| 5.0 | 2 | 0.2 | 5.1% [3.7%, 6.9%] | 1.8% [1.0%, 3.1%] | 29.9% [27.6%, 32.2%] |
| 5.0 | 2 | 0.4 | 4.7% [3.4%, 6.4%] | 10.0% [7.9%, 12.6%] | 35.4% [33.0%, 37.9%] |
| 20.0 | 5 | 0.0 | 3.4% [2.3%, 5.0%] | 2.4% [1.5%, 3.9%] | 32.4% [30.1%, 34.8%] |
| 20.0 | 5 | 0.05 | 3.3% [2.2%, 4.8%] | 2.6% [1.6%, 4.1%] | 32.3% [29.9%, 34.7%] |
| 20.0 | 5 | 0.2 | 3.2% [2.1%, 4.7%] | 2.6% [1.6%, 4.1%] | 32.3% [29.9%, 34.7%] |
| 20.0 | 5 | 0.4 | 3.8% [2.7%, 5.5%] | 1.0% [0.4%, 2.1%] | 31.1% [28.8%, 33.5%] |

At 5 Hz the default `min_settle_samples = 5` starves the oracle: ordinary successes turn UNKNOWN as soon as samples drop (25% at 5% loss, 91% at 40%). Set `min_settle_samples` to fit the rate (2 here) and they stay near 1% to 10%, at the cost of a slightly higher false-pass rate (3.4% to 5.1%) since fewer samples reveal less. At 20 Hz dropped samples barely matter.


## Place: video clock off by up to this many seconds

| offset (s) | false passes | UNKNOWN of ordinary successes |
|---|---|---|
| 0.0 | 3.3% [2.2%, 4.8%] | 2.2% [1.3%, 3.7%] |
| 0.15 | 3.3% [2.2%, 4.8%] | 2.4% [1.5%, 3.9%] |
| 0.5 | 3.4% [2.3%, 5.0%] | 1.9% [1.1%, 3.3%] |
| 1.0 | 3.7% [2.6%, 5.3%] | 9.3% [7.2%, 11.8%] |

The video clock can be off by up to half a second without effect; at a full second ordinary successes start to turn UNKNOWN (9%).


## Place: share of trials where another object lands on the plate mid-trial

| foreign_object weight / total | TaskWitness false passes | vision-only false passes |
|---|---|---|
| 0 / 97 | 0.0% [0.0%, 0.6%] | 52.0% [48.2%, 55.7%] |
| 3 / 100 | 3.3% [2.2%, 4.8%] | 53.8% [50.2%, 57.4%] |
| 10 / 107 | 11.8% [9.7%, 14.3%] | 53.4% [49.9%, 56.8%] |
| 20 / 117 | 20.1% [17.6%, 23.0%] | 52.0% [48.6%, 55.4%] |

The residual risk. If another object of about the right weight lands on the plate during the trial, TaskWitness's false passes grow with how often that happens: roughly the same share of real failures as the share of such trials (3 of 100 gives 3.3%, 20 of 117 gives 20%). The load cell cannot tell objects apart; a physical guard, or a second sensor that identifies the object, is the mitigation.


## Button press: rig quality

| rig | TaskWitness false passes | vision-only false passes | TaskWitness false fails | TaskWitness UNKNOWN (all) |
|---|---|---|---|---|
| clean | 0.0% [0.0%, 0.6%] | 79.8% [76.5%, 82.8%] | 0.0% [0.0%, 0.4%] | 18.0% [16.1%, 20.0%] |
| lab | 0.0% [0.0%, 0.6%] | 79.8% [76.5%, 82.8%] | 0.0% [0.0%, 0.4%] | 18.1% [16.3%, 20.2%] |
| noisy | 0.0% [0.0%, 0.6%] | 79.5% [76.1%, 82.5%] | 0.0% [0.0%, 0.4%] | 18.3% [16.5%, 20.4%] |

Button press, by rig quality: no false passes in any rig, against about 80% for vision-only (a tool hovering over, brushing or holding the button looks like success). The 18% UNKNOWN is the deliberately ambiguous modes: a press still held at the end, an unobserved switch, a press by something other than the robot.


## Button press: switch sampling rate (a contact can only be bracketed between samples; an unresolvable hold is UNKNOWN)

| switch Hz | false passes | light brushes counted as presses | light brushes left UNKNOWN | false fails | UNKNOWN (all) |
|---|---|---|---|---|---|
| 20.0 | 0.0% [0.0%, 0.6%] | 0 / 111 | 65 / 111 | 0.0% [0.0%, 0.4%] | 26.6% [24.4%, 28.9%] |
| 50.0 | 0.0% [0.0%, 0.6%] | 0 / 111 | 50 / 111 | 0.0% [0.0%, 0.4%] | 21.0% [19.0%, 23.1%] |
| 100.0 | 0.0% [0.0%, 0.6%] | 0 / 111 | 21 / 111 | 0.0% [0.0%, 0.4%] | 18.1% [16.3%, 20.2%] |
| 500.0 | 0.0% [0.0%, 0.6%] | 0 / 111 | 0 / 111 | 0.0% [0.0%, 0.4%] | 16.7% [14.9%, 18.6%] |

Sampling only brackets a contact's duration, so a slow switch cannot confirm a short contact. TaskWitness never calls a brush a press at any rate; the price of a slow switch is UNKNOWN: 65 of 111 light brushes are left UNKNOWN at 20 Hz against 0 at 500 Hz, and UNKNOWN overall rises from 16.7% to 26.6%. (An earlier version estimated duration from sample spacing and counted 37 of 111 brushes as presses at 20 Hz; the study found that and it was fixed.)


## Planning: trials until the anytime-valid test says TaskWitness has fewer false passes than vision-only (lab rig, alpha 0.05)

| runs | decided within 600 trials | median trials | 90th percentile |
|---|---|---|---|
| 100 | 100/100 | 31.0 | 48 |

A planning number: how many trials the anytime-valid sequential test needs before it can say TaskWitness has fewer false passes than the vision-only check on a lab rig. Median 31, 90th percentile 48, in all 100 runs within 600. This is an optimistic figure because the baseline here is weak; against a stronger judge the differences are fewer and more trials are needed.


## What this does not show

- **The failure modes and noise levels are assumptions.** The mix (for example 8% of trials ending with the object still held) and every noise figure are the author's choices, except the wrist-sensor numbers, which come from real data ([REAL_DATA.en.md](REAL_DATA.en.md)). Different mixes give different rates; the study is about how the method *moves*, and what it cannot resolve, not about absolute rates.
- **The oracles and the simulator share an author**, so they share blind spots. The study found real bugs (a leftover object counted as a success, slow switch sampling counting brushes as presses, a press cap ignoring an unresolved contact), which is what it is for, but a simulator cannot find a failure its author did not imagine.
- **No sensor was ever real here.** Nothing in this file says a load cell or a button switch behaves like the simulated one. Real validation needs the experiment in [EXPERIMENT_GUIDE.en.md](EXPERIMENT_GUIDE.en.md).
- **The vision-only baseline is weak by construction** (see above).

## Reproduce

```bash
python examples/simulation/study.py                     # all tables
python examples/simulation/study.py --n 400             # quicker
taskwitness simulate place --n 1000 --preset lab --set load_noise_g=1.0 --out sim
taskwitness evaluate sim --by failure_mode --order-by trial
```

Presets: `clean`, `lab`, `noisy`, `wrist_ft`; any setting can be overridden with `--set NAME=VALUE`.
