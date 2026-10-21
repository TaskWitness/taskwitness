[简体中文](ROADMAP_90_DAYS.md) · **English**

# TaskWitness 90-day roadmap

Start date: 2026-10-21. Principle: every phase has checkable acceptance criteria, and nothing unfinished is listed as an existing feature in the README.

## D1–7: Open-source launch (no hardware)

- [x] PlaceOracle, evidence fusion, explicit UNKNOWN
- [x] CLI (verify / batch / check), deterministic evidence bundles, SHA-256 integrity check
- [x] 5 synthetic episodes (1 PASS, 2 FAIL, 2 UNKNOWN), automated tests, GitHub CI
- [ ] Pick public robot-manipulation videos, label outcomes by hand, and make a first assessment of how vision-only judging goes wrong
- [ ] Check the PyPI name, domain and trademarks in target markets

**Done when:** a stranger runs the README quickstart unaided, and at least 5 target developers have given feedback.

## D8–30: Real experiments (phone + load cell)

- [ ] Build the WitnessNode prototype (see `hardware/README.en.md`): load-cell module + microcontroller + USB serial
- [x] Sensor adapter: turn serial readings into `taskwitness.episode/v0` (`taskwitness ingest`, v0.2)
- [x] Load-cell and camera calibration (`taskwitness calibrate`, v0.2)
- [x] Phone video + simple object detection that outputs `object_xy` and confidence (colour-blob baseline `taskwitness track`, v0.2; not yet validated on real footage)
- [ ] Move a block by hand to imitate the robot, collect at least 200 trials, each labeled by an independent annotator
- [ ] **Fix in advance** the test conditions, thresholds and metrics, then compare: vision only / load cell only / fusion (config freezing and statistics are ready: `--config`, `taskwitness evaluate`; see the [experiment guide](EXPERIMENT_GUIDE.en.md))

**Metrics:** false-pass rate, false-fail rate, UNKNOWN rate (coverage), human time per trial.

**Done when:** under the pre-set conditions and coverage, we know whether fusion significantly reduces false passes. Results are published whether good or bad.

## D31–60: Ecosystem

- [ ] WitnessNode wiring diagram, BOM and firmware, all open source
- [x] One evaluation-framework plugin, integrated as an external result judge (Inspect Robots scorers, v0.2)
- [ ] LeRobot dataset adapter (today: export per-episode scores and compare with `taskwitness audit`)
- [ ] Reach developers with open-source arms such as SO-101 and give them reproduction scripts and the sensor design
- [x] `ButtonPressOracle` (v0.2)

**Done when:** at least 2 external real-robot test setups have agreed to run the experiment and report back.

## D61–90: Publish results and community reproduction

- [ ] Publish the full data, labels, thresholds and results of the D8–30 real experiments, including cases where TaskWitness is wrong
- [ ] First WitnessBench release: a place-task dataset with load-cell data and independent labels
- [ ] Collect reproduction results from external robot setups
- [ ] Only after reproducible real results exist: Show HN, relevant Reddit communities and a Hugging Face Space
- [x] Evidence-bundle signing (Ed25519, `taskwitness sign`, v0.2; a signature proves origin, not correctness)
- [ ] Anytime-valid sequential tests and finite-sample PPI bounds (see [research notes](RESEARCH.en.md))

**Done when:** at least 1 real experiment result has been independently reproduced by an outside contributor and published.

## 90-day open-source checklist

- [ ] Fusion shows a clear gain on an independent test set (controlling for UNKNOWN rate, scenario difficulty and coverage)
- [ ] At least 2 external real-robot test setups
- [ ] At least 1 independent external reproduction
- [ ] Total human cost goes down (counting fixture calibration, scene reset and false-alarm review)

**Launch metrics:** actual installs, external reproductions, external contributions. Stars are for reference only.

## Explicitly out of scope

General robot control, training VLAs, building our own simulator, custom PCBs, multi-tenant SaaS.
