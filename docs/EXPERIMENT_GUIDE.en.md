[简体中文](EXPERIMENT_GUIDE.md) · **English**

# Experiment guide: from a real rig to an honest result

This is the protocol for the Day 8-30 experiment (phone camera + load cell, at
least 200 independently labeled place attempts). Every step uses a command that
exists today. The hardware itself is described in [hardware/README.en.md](../hardware/README.en.md).

```
record logs ─► calibrate ─► track video ─► ingest ─► label ─► verify / evaluate / estimate
```

## Before you build anything: rehearse with the simulator

```bash
taskwitness simulate place --n 500 --preset lab --set load_noise_g=1.0 --out sim
taskwitness evaluate sim --by failure_mode --order-by trial
```

It generates episodes with known ground truth at the noise level you expect, so you
can see how many trials a decision needs, which failure modes land in UNKNOWN, and
whether your sample rate and thresholds are adequate, before collecting real data.
Its failure modes and noise levels are assumptions: see [SIMULATION.en.md](SIMULATION.en.md).
Do not use the simulator's numbers as results.

## 0. Freeze the plan before collecting data

Write down, and commit to git *before* the first trial:

- the task (object, mass, target zone) as `task.json`;
- the oracle thresholds as `config.json`. Its SHA-256 appears in every report
  as `config_sha256`, so readers can check you did not tune thresholds on the results;
- the failure modes you will stage (for example `none`, `not_released`, `bounce`,
  `edge`, `occluded`) and how many trials of each;
- the primary metric: conditional miss rate (false passes among real failures)
  of TaskWitness versus vision only, tested with the exact McNemar test.

```json
{"place": {"settle_window_s": 1.0, "min_settle_samples": 5, "stability_std_g": 2.0}}
```

## 1. Calibrate the load cell

Record 10-20 s of raw readings with the plate empty, then with at least two
reference masses. Logs are `t_ms,raw` lines, as any serial logger writes them.

```bash
taskwitness calibrate load-cell --empty empty.csv \
    --ref 100=ref100.csv --ref 500=ref500.csv --out loadcell.cal.json
```

The output reports noise, residuals and `suggested_place_config`. If the max
error is more than a few grams, fix the mechanics (rigid plate, no cable
strain) before going on.

Then set the oracle thresholds from known-good recordings instead of guessing.
Record the empty plate and the object resting on it, ideally in several
sessions (at least 19 one-second windows per kind at the default alpha = 0.05;
a minute of logging gives ~59):

```bash
taskwitness calibrate thresholds --empty empty.csv --object 52=block.csv \
    --load-cell-cal loadcell.cal.json --alpha 0.05 --out thresholds.json
```

A new known-good window exceeds each threshold with probability at most alpha,
if the rig does not drift between calibration and the experiment. Copy the
`config` block into `config.json` now, not after seeing results.

## 2. Calibrate the camera

Mark at least four points on the plate (corners work), read their pixel
positions in one frame and measure them in the plate frame, in the same units
as `target_zone`:

```json
[{"pixel": [102, 88], "plate": [0.0, 0.0]}, {"pixel": [538, 95], "plate": [0.3, 0.0]},
 {"pixel": [551, 410], "plate": [0.3, 0.2]}, {"pixel": [95, 402], "plate": [0.0, 0.2]}]
```

```bash
taskwitness calibrate camera --points points.json --out camera.cal.json
```

The reprojection error is in plate units; it should be well below the zone size.

## 3. Record each trial

- Start every trial with a **sync tap**: tap the plate once where the camera can
  see it. The load spike and the video frame of the tap give the clock offset
  between video and sensors (`--video-offset-s`).
- Log the load cell (`t_ms,raw`) and, if available, the gripper (`t_ms,open|closed`)
  on the same clock.
- Record video at a constant frame rate (re-encode phone video if needed).
- Do not look at TaskWitness output while collecting.

## 4. Track the object in the video

```bash
taskwitness track trial-001.mp4 --color 200,40,40 --tolerance 60 \
    --roi 80,60,560,420 --camera-cal camera.cal.json --out trial-001.video.json
```

Check a few frames by eye. A region of interest around the plate removes most
false detections.

## 5. Build the episode

```bash
taskwitness ingest place --task task.json --id trial-001 \
    --load-cell trial-001.load.csv --load-cell-cal loadcell.cal.json \
    --gripper trial-001.gripper.csv \
    --video trial-001.video.json --video-offset-s 0.42 \
    --claim true --tag failure_mode=bounce --out episodes/trial-001.json
```

The episode records the SHA-256 of every source file under `provenance`, so the
bundle's evidence digest covers the raw data. Strict parsing is the default; use
`--lenient` only if you also report how many lines were skipped.

## 6. Label independently

A person who did not run the trial and does not see TaskWitness output labels
each trial PASS or FAIL from direct inspection, and the label is added with
`--label`. For `estimate`, label a **uniformly random subset** chosen before
labeling starts; do not pick "interesting" trials.

## 7. Verify, evaluate, estimate

```bash
taskwitness batch episodes --config config.json --out batch.json
taskwitness evaluate episodes --config config.json --by failure_mode --out eval.json
taskwitness estimate episodes --config config.json --out estimate.json
```

Report, together:

- conditional miss (false passes among real failures) and false fail, with
  95% intervals, for TaskWitness and for vision only;
- the UNKNOWN rate: a low miss rate bought with a high UNKNOWN rate is not a win;
- absolute misses and audit coverage, and the per-failure-mode breakdown;
- the McNemar p-value for paired false passes and, if you want to stop early,
  the sequential test: `taskwitness evaluate ... --order-by trial` reads the
  episodes in trial order (a numeric `--tag trial=N` set at ingest) and reports
  whether, and at which discordant pair, it rejects "no difference" with the
  type-I error held at alpha however often you looked. Fix the order and alpha
  in step 0, not after;
- `config_sha256` and the list of evidence digests.

`estimate` prints several valid intervals (labels only, prediction-powered,
asymptotic and finite-sample). Decide which one you will report in step 0:
choosing the narrowest after seeing them voids its coverage. Prediction-powered
intervals only help with an accurate judge and thousands of episodes; at the
size of a small experiment, labels alone are usually narrower.

Publish results whether they favor TaskWitness or not.

## 8. Audit another judge on the same episodes

Export any judge's per-episode score (Robometer success probability, TOPReward,
a VLM's verdict) as `episode_id,score` and run:

```bash
taskwitness audit --judge robometer.csv --episodes episodes --by failure_mode --out audit.json
```

You get its false passes, balanced accuracy, ROC-AUC, calibration error and
success bias against your labels, plus a paired comparison with TaskWitness.

## If your trials are already in a LeRobot dataset

Instead of steps 3 to 5, map the dataset's columns to sensor streams and convert it
(needs `pip install "taskwitness[lerobot]"` and the dataset's `meta/` and `data/` folders; the videos are not read):

```bash
taskwitness lerobot path/to/dataset --mapping mapping.json --out episodes
```

The mapping names the columns that become `load_cell`, `gripper_width`, `button` or
`gripper`, an optional column that splits a long recording into one episode per
action (`segments`), the human label column and a task-text filter. A worked example
for REASSEMBLE is in `examples/lerobot/reassemble_pick_mapping.json` (its object band is a placeholder: set your object's real band, or per-object bands as `examples/real_data/reassemble_grasp.py` does); the field list
is in the module docstring of `taskwitness.integrations.lerobot`. Each episode records
the SHA-256 of the data files it came from. To track an object in the episode's slice
of a concatenated camera video, use `taskwitness track VIDEO --start-s S --end-s E`
with the span that `LeRobotDataset.video_span` returns.

## 9. Optional: sign the bundles

```bash
taskwitness keygen --dir keys
taskwitness verify episodes/trial-001.json --out bundles/trial-001.json
taskwitness sign bundles/trial-001.json --key keys/taskwitness.key --out bundles/trial-001.sig.json
taskwitness verify-signature bundles/trial-001.json bundles/trial-001.sig.json --public-key keys/taskwitness.pub
```

A signature shows the bundle came from your key unchanged. It does not show the
verdict is right.
