[简体中文](README.md) · **English**

# WitnessNode hardware notes (draft)

Status: **design notes only.** No firmware or wiring has been built or tested
yet. The host-side software exists: `taskwitness calibrate` and `taskwitness ingest`. Part choices below are starting points for the Day 8-30 experiment,
not a validated bill of materials.

## Goal

The cheapest sensor setup that gives `PlaceOracle` independent physical evidence:
a rigid plate under the target zone that reports weight over time on a clock
shared with the camera.

## First prototype

| Part | Purpose | Notes |
| --- | --- | --- |
| Bar load cell (1-5 kg range) | Measures weight on the target plate | Pick a range close to the heaviest test object for resolution. |
| HX711 24-bit ADC breakout | Reads the load cell | Common, cheap; 10 or 80 samples/s modes. |
| Microcontroller with USB serial (e.g. ESP32 or Arduino-class board) | Streams timestamped readings | Off-the-shelf only; no custom PCB in the first 90 days. |
| Rigid plate (acrylic/MDF) + spacer | Defines the target zone | Plate outline must match `task.target_zone` after calibration. |
| Phone or USB camera | Video evidence | Fixed mount; record the plate and a visible clock or sync marker. |

## Data contract

The node should emit one line per sample, e.g. `t_ms,raw` (raw ADC counts). Save it
with any serial logger, then:

```bash
taskwitness calibrate load-cell --empty empty.csv --ref 100=ref100.csv --ref 500=ref500.csv --out loadcell.cal.json
taskwitness ingest place --task task.json --id trial-001 --load-cell trial-001.csv --load-cell-cal loadcell.cal.json --out trial-001.json
```

Formats: [../docs/EVIDENCE_SPEC.en.md](../docs/EVIDENCE_SPEC.en.md); the full workflow:
[../docs/EXPERIMENT_GUIDE.en.md](../docs/EXPERIMENT_GUIDE.en.md). Firmware and a live recorder are not written yet.

## Calibration checklist

1. Tare with the empty plate, then scale with at least two reference masses
   (`taskwitness calibrate load-cell` reports noise, residuals and suggested thresholds).
2. Record the calibration masses and residual error with each experiment batch.
3. Measure noise (std-dev) on an empty settled plate; `stability_std_g` must sit
   comfortably above it.
4. Measure the time from object release to a settled reading; `settle_window_s`
   and the episode end time must allow for it.
5. Synchronise clocks: start each episode with a tap on the plate visible to the
   camera, and align the load spike to the video frame.

For button tasks, read the button's own contact (for example on a microcontroller
digital input), log it as `t_ms,1|0`, and import it with `taskwitness ingest button_press`.

## Known limitations

- A single plate cannot tell *where* on the plate the object rests; the plate
  outline itself is the zone.
- Vibration from the robot base can couple into the load cell; isolate the plate.
- Objects lighter than a few grams are below the default `empty_threshold_g`.
