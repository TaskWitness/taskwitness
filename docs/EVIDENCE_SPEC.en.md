[简体中文](EVIDENCE_SPEC.md) · **English**

# Evidence specification (v0)

TaskWitness reads and writes versioned JSON documents, each identified by its
`schema` field. v0 may change without notice until v1.

| Schema | Produced by | Purpose |
| --- | --- | --- |
| `taskwitness.episode/v0` | you, `ingest`, integrations | Input: task spec + evidence streams |
| `taskwitness.evidence/v0` | `verify`, `batch` | Output: verdict + evidence bundle |
| `taskwitness.video/v0` | `track` | Object / tool positions per frame |
| `taskwitness.calibration/v0` | `calibrate` | Load-cell or camera calibration |
| `taskwitness.thresholds/v0` | `calibrate thresholds` | Conformal oracle thresholds + a ready-to-use `config` block |
| `taskwitness.signature/v0` | `sign` | Ed25519 signature over a bundle |

## Episode: `taskwitness.episode/v0`

### Place task

```json
{
  "schema": "taskwitness.episode/v0",
  "episode_id": "01_clean_success",
  "task": {
    "type": "place",
    "object": {"name": "red_block", "mass_g": 52.0},
    "target_zone": {"x_min": 0.30, "x_max": 0.40, "y_min": -0.05, "y_max": 0.05}
  },
  "claim": {"source": "policy_self_report", "success": true},
  "video": [{"t": 0.0, "object_xy": [0.10, 0.20], "confidence": 0.9}],
  "sensors": {
    "load_cell": [{"t": 0.0, "grams": 0.1}],
    "gripper": [{"t": 0.0, "state": "closed"}]
  },
  "tags": {"failure_mode": "none"},
  "label": {"verdict": "PASS", "note": "independent human label"}
}
```

### Button-press task

```json
{
  "schema": "taskwitness.episode/v0",
  "episode_id": "b01_clean_press",
  "task": {
    "type": "button_press",
    "button": {"name": "start_button", "expected_presses": 1, "max_presses": 1,
               "zone": {"x_min": 0.50, "x_max": 0.56, "y_min": 0.10, "y_max": 0.16}}
  },
  "video": [{"t": 0.0, "tool_xy": [0.20, 0.40], "confidence": 0.9}],
  "sensors": {"button": [{"t": 0.0, "pressed": false}]}
}
```

### Fields

| Field | Required | Notes |
| --- | --- | --- |
| `schema`, `episode_id`, `task` | yes | `episode_id` is a non-empty string. |
| `task.type` | yes | `place` or `button_press`. |
| `task.object.mass_g` | place | Positive. Used for load matching. |
| `task.target_zone` | place | Axis-aligned box in the frame of `video[].object_xy`. The load cell is assumed to sit under exactly this zone. |
| `task.button.expected_presses` | no | Integer >= 1, default 1. |
| `task.button.max_presses` | no | Integer >= `expected_presses`; more presses are a FAIL. |
| `task.button.zone` | if video | Where the tool must be seen for video to support a press. |
| `claim.success` | no | The robot's own claim (`true`, `false` or `null`). Never used to decide. |
| `video` | no | Pre-computed positions (`object_xy` for place, `tool_xy` for button) with confidence in [0, 1]. |
| `sensors.load_cell` | place | Grams on the target plate. Without it a place verdict is always UNKNOWN. |
| `sensors.gripper` | no | `open` / `closed`. |
| `sensors.button` | button | `pressed: true/false`, the button's own contact. Without it a button verdict is always UNKNOWN. |
| `tags` | no | Free-form strings, e.g. `failure_mode`; `evaluate --by` groups by them. |
| `provenance` | no | Written by `ingest`: tool version, `t0_ms`, SHA-256 of every source file. |
| `label` | no | Ground truth for evaluation. Stripped before judging and excluded from `evidence_sha256`. |

All numbers must be finite: NaN and infinity are rejected even though Python's
JSON parser accepts them. Timestamps `t` are seconds on a shared clock. Extra
fields are allowed and covered by the evidence digest.

### How ButtonPressOracle counts presses

A press is a contact run that starts after an open sample (a rising edge),
lasts at least `min_hold_s` and ends with a release. Gaps and runs shorter
than `debounce_s` are bounce and are merged or ignored. A contact still closed
at the last sample means the press never completed (UNKNOWN). If fewer presses
than required were seen and the switch stream has a gap longer than `max_gap_s`
(including at the episode edges), the result is UNKNOWN, not FAIL.

## Evidence bundle: `taskwitness.evidence/v0`

| Field | Meaning |
| --- | --- |
| `oracle` | `PlaceOracle` or `ButtonPressOracle`. |
| `verdict` | `PASS`, `FAIL` or `UNKNOWN`. |
| `reasons` | Ordered human-readable reasons; the first is the headline. |
| `claim.robot_claimed_success` | Copied from the episode. |
| `claim.contradicted` | True when the claim is `true` and the verdict is FAIL, or the claim is `false` and the verdict is PASS. |
| `comparison.vision_only_verdict` | What a judge using only the video oracle would say. For analysis; not used in the verdict. |
| `oracles[]` | Each oracle's `state`, `detail` and raw `measurements`. |
| `timeline[]` | Key events: gripper open, load on/off, press/release. |
| `config` | Every threshold used. |
| `integrity.evidence_sha256` | SHA-256 of the canonical JSON of the episode minus `label`. |
| `integrity.bundle_sha256` | SHA-256 of the canonical JSON of the bundle minus this field. |

Canonical JSON: keys sorted, separators `,` and `:`, UTF-8, no extra whitespace.

## Config file

```json
{"place": {"settle_window_s": 1.0}, "button_press": {"min_hold_s": 0.05}}
```

Keys are task types; fields are those of `PlaceOracleConfig` and
`ButtonPressConfig`. Unknown keys, non-numbers and negative values are
rejected. Reports carry `config_sha256`, the digest of the full resolved config.

## Sensor logs (input to `ingest` and `calibrate`)

One sample per line, `t_ms,value`. Blank lines and `#` comments are skipped; a
single header line is allowed. Values: load cell raw counts (with a
calibration) or grams; gripper `open|closed`; button `1|0`, `true|false` or
`pressed|released`.

## Video observations: `taskwitness.video/v0`

```json
{"schema": "taskwitness.video/v0", "coords": "pixel",
 "frames": [{"t": 0.0, "xy": [312.5, 220.0], "confidence": 0.93}, {"t": 0.033, "xy": null, "confidence": 0.0}]}
```

`coords` is `pixel` or `plate`. Pixel coordinates need a camera calibration
during `ingest`; frames with `xy: null` (no detection) are dropped and counted.

## Calibration: `taskwitness.calibration/v0`

Either `load_cell` (`tare_raw`, `counts_per_gram`, `noise_std_g`,
`residual_rms_g`, `max_abs_error_g`, `references`, plus
`suggested_place_config`) or `camera` (`homography` 3x3, `rms_error`,
`max_error`, `points`).

## Signature: `taskwitness.signature/v0`

`algorithm` (`ed25519`), `bundle_sha256`, `evidence_sha256`, `key_id` (first 16
hex characters of SHA-256 of the raw public key), `public_key` and `signature`
(base64). The signature covers the canonical JSON of the whole bundle.
`verify-signature --public-key` pins the key you trust; without it the
embedded key is only checked for self-consistency.

The digests detect edits; signatures bind a bundle to a key. Neither proves a
verdict is correct.
