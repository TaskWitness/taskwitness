[简体中文](RESEARCH.md) · **English**

# Research notes: what recent work means for TaskWitness

Snapshot as of 2026-10-21. Numbers below are taken from the papers' abstracts
or from the released code of the frameworks named; read the papers before
citing them further. Each section ends with what TaskWitness does about it.

## 1. Vision judges fail exactly where it matters

- **FailBench** (Navasardyan et al., arXiv [2609.03611](https://arxiv.org/abs/2609.03611), Sep 2026):
  2,197 manipulation attempts from 14 public sources, 13 VLM-based detectors.
  The best reaches only **0.77 mean balanced accuracy**; detectors fine-tuned for
  failure detection underperform general-purpose VLMs; performance drops to
  **near chance (< 0.60)** on contact-intensive assembly; and there is a
  **systematic bias toward predicting success under ambiguous evidence** that
  more reasoning effort does not remove. Cropping outcome-relevant regions helps
  the top detector by 2.4 points.
- **Coverage shift** (Guan et al., arXiv [2610.24801](https://arxiv.org/abs/2610.24801), Oct 2026):
  as a tray-placement policy improves from 66.8% to 97.0% success, a fixed VLM
  judge accepts **50.0% of the remaining hover failures, up from 31.1%**. The
  surviving failures hide below the tray rim (148/160 below-rim hovers accepted
  vs 0/160 above-rim). The authors recommend reporting **absolute misses,
  conditional misses and audit coverage together**.
- Failure-reasoning VLMs such as **Guardian** (arXiv [2512.01946](https://arxiv.org/abs/2512.01946))
  and **AHA** (arXiv [2410.00371](https://arxiv.org/abs/2410.00371)) improve
  through large synthetic failure datasets, but still only see pixels.

**TaskWitness response.** Physical evidence decides; video may only veto. A
hovering tool (button) or an unreleased object (place) is a FAIL regardless of
what the camera suggests. `taskwitness evaluate --by <tag>` reports absolute
misses, conditional misses and audit coverage per failure mode, exactly as
2610.24801 recommends. `taskwitness audit` measures `pass_rate_bias`, the
"success under ambiguity" bias FailBench found. The tracker supports a region of
interest, the same outcome-region idea that helped in FailBench.

## 2. Success detection is now built into the frameworks

- **LeRobot v0.6** (Hugging Face, July 2026) ships a reward-model API
  (`lerobot.rewards`, verified in the 0.6.1 package) with a classifier, SARM,
  **Robometer** and **TOPReward**.
  - Robometer (arXiv [2603.02115](https://arxiv.org/abs/2603.02115)) trains
    progress and success heads with trajectory-comparison preferences on
    RBM-1M, over one million trajectories including many failures.
  - TOPReward (arXiv [2602.19313](https://arxiv.org/abs/2602.19313)) is
    training-free: it reads a video-language model's token probability that the
    instruction was completed, evaluated on ManiRewardBench (130 tasks, four
    robot platforms).
- **Inspect Robots** (Robocurve, `inspect-robots` 0.60, verified in source):
  benchmarks defined once and run on any robot or simulator; scorers are pure
  readers of a recorded trial; human operator verdicts and a VLM grader are
  built in; plugins register through entry points.

**TaskWitness response.** Do not compete on "automatic success detection".
Be the independent physical reference that those judges can be checked
against. `taskwitness audit` takes any judge's per-episode scores (Robometer,
TOPReward, a VLM, an operator) and reports false passes, balanced accuracy,
ROC-AUC, calibration error and success bias against human labels, and runs an
exact McNemar test against TaskWitness on the same episodes. TaskWitness ships
`taskwitness` / `taskwitness_unknown` scorers for Inspect Robots, tested inside
a real `inspect_robots.eval()` loop.

## 3. Which signals actually carry the truth

- **Observability of silent failures** (Bedi, arXiv [2606.03134](https://arxiv.org/abs/2606.03134), Jun 2026):
  among episodes a robot flagged as successful, false successes in cube transfer
  were almost fully recoverable from joint data alone, but only partly in peg
  insertion, where vision closed most of the gap. The author warns the
  proprioceptive separation relies on velocity differences far below realistic
  sensor noise: an optimistic upper bound from a noiseless simulator.

**TaskWitness response.** The robot's own proprioception is part of the system
under test and is noisy in reality. TaskWitness uses separate, low-cost
external sensors (a load cell under the target, the button's own contact) whose
signal is large relative to noise. Sensor dropouts and gaps produce UNKNOWN
rather than a guess.

## 4. Verifiers need verification

- **No Free Checker** (Wan et al., arXiv [2609.09250](https://arxiv.org/abs/2609.09250), Sep 2026)
  surveys about 150 verifiers. Across human, rule-based and formal, learned, and
  model-intrinsic verifiers, **credibility falls as availability rises**: cheaper,
  earlier, denser verdicts are easier to game. Verifiers are validated by
  agreement with human labels, the performance of the policies they train, and
  behaviour under reward hacking.

**TaskWitness response.** TaskWitness is deliberately on the high-credibility,
lower-availability end: it needs a sensor and gives one verdict per episode.
Its claims are made checkable: agreement with human labels comes with confidence
intervals, thresholds are frozen in a config whose digest goes into every
report, and bundles are deterministic and tamper-evident. **Open problem:** a
policy optimized against TaskWitness could learn to game it (for example by
pressing on the plate). The PlaceOracle already returns UNKNOWN when the
gripper is still closed on a full load; a systematic red-team of the oracles is
future work.

## 5. Honest statistics with few real trials

- **STEP** (Snyder et al., arXiv [2503.10966](https://arxiv.org/abs/2503.10966)):
  sequential policy comparison with near-optimal stopping, up to 32% fewer trials.
- **N-SCORE** (Snyder et al., arXiv [2603.13616](https://arxiv.org/abs/2603.13616), RSS 2026):
  safe, anytime-valid inference beyond binary success, up to 70% less
  evaluation effort than batch methods.
- **SureSim** (Badithela et al., arXiv [2510.04354](https://arxiv.org/abs/2510.04354)):
  prediction-powered inference with paired real and simulated trials, 20-25%
  fewer hardware trials.
- **Prediction-powered inference** (Angelopoulos et al., arXiv [2301.09633](https://arxiv.org/abs/2301.09633)):
  valid confidence intervals from many machine predictions plus a few labels.

**TaskWitness response.** Every rate comes with a Wilson interval. Comparisons
of two judges on the same episodes use an exact McNemar test, so "fusion beats
vision" is only claimed when the paired data supports it; on the bundled
synthetic examples it is deliberately *not* significant (p = 0.0625).
`taskwitness estimate` applies prediction-powered inference: TaskWitness
verdicts on every episode plus human labels on a random subset give a success
rate with a valid interval. **Not yet implemented:** anytime-valid sequential
tests (STEP / N-SCORE) and finite-sample PPI bounds (SureSim uses
Waudby-Smith-Ramdas bounds; TaskWitness uses the asymptotic CLT interval).

## 6. Runtime failure prediction is complementary

- **FIPER** (arXiv [2510.09459](https://arxiv.org/abs/2510.09459)) and
  **FAIL-Detect** (arXiv [2503.08558](https://arxiv.org/abs/2503.08558)) predict
  failures *during* a rollout from policy-internal signals, calibrated with
  conformal prediction on successful rollouts only.

**TaskWitness response.** Different job: TaskWitness verifies the *outcome*
from outside the policy. The conformal idea, calibrating thresholds from
recordings of known-good states, fits TaskWitness's load-cell thresholds and is
a candidate for a future `calibrate thresholds` command.

## 7. Provenance is not correctness

Supply-chain tooling (in-toto attestations, Sigstore) has made signed
provenance routine. A signature shows who produced an artifact and that it was
not changed; it does not show the content is right.

**TaskWitness response.** `taskwitness sign` / `verify-signature` add Ed25519
signatures over evidence bundles, with the trusted key pinned explicitly, and
the documentation states what a signature does not prove.

## Open questions we want real data for

1. On real hardware, how much does load-cell + vision fusion reduce conditional
   misses compared with vision alone, and at what UNKNOWN rate?
2. Which failure modes stay hard for physical sensors (light objects, objects
   resting on the zone edge, vibration)?
3. How do Robometer / TOPReward scores on the same episodes compare with
   TaskWitness verdicts, per failure mode?
4. Does physical verification stay robust when a policy is trained against it?
