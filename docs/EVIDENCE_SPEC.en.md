[简体中文](EVIDENCE_SPEC.md) · **English**

# Evidence specification (v0)

Two JSON documents: the **episode** (input) and the **evidence bundle** (output).
Both are versioned by their `schema` field. v0 may change without notice until v1.

## Episode: `taskwitness.episode/v0`

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
  "label": {"verdict": "PASS", "note": "independent human label"}
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `schema`, `episode_id`, `task` | yes | `task.type` must be `place` for `PlaceOracle`. |
| `task.object.mass_g` | yes | Positive. Used for load matching. |
| `task.target_zone` | yes | Axis-aligned box in the same frame as `video[].object_xy` (metres in the examples). The load cell is assumed to sit under exactly this zone. |
| `claim` | no | The robot's own claim. Never used to decide. |
| `video` | no | Pre-computed object positions with confidence in [0, 1]. |
| `sensors.load_cell` | no* | Grams on the target plate. *Without it the verdict is always UNKNOWN. |
| `sensors.gripper` | no | `open` / `closed`. |
| `label` | no | Ground truth for evaluation. Stripped before judging and excluded from `evidence_sha256`. |

Timestamps `t` are seconds on a shared clock. The episode ends at the latest
timestamp across all streams. Extra fields are allowed and are covered by the
evidence digest.

## Evidence bundle: `taskwitness.evidence/v0`

| Field | Meaning |
| --- | --- |
| `verdict` | `PASS`, `FAIL` or `UNKNOWN`. |
| `reasons` | Ordered human-readable reasons; the first is the headline. |
| `claim.robot_claimed_success` | Copied from the episode. |
| `claim.contradicted` | True when the claim is `true` and the verdict is FAIL, or the claim is `false` and the verdict is PASS. |
| `comparison.vision_only_verdict` | What a judge using only the video oracle would say. For analysis; not used in the verdict. |
| `oracles[]` | Each oracle's `state`, `detail` and raw `measurements` (window, mean, std, ratios, ...). |
| `timeline[]` | Key events: gripper open, load on/off, last sensor sample. |
| `config` | Every threshold used. |
| `integrity.evidence_sha256` | SHA-256 of the canonical JSON of the episode minus `label`. |
| `integrity.bundle_sha256` | SHA-256 of the canonical JSON of the bundle minus this field. |

Canonical JSON: keys sorted, separators `,` and `:`, UTF-8, no extra whitespace.

`taskwitness check bundle.json --episode episode.json` recomputes both digests.
The digests detect accidental or naive edits; they are not signatures. Anyone can
recompute them, so they do not prove *who* produced a bundle. Signed bundles are
future work.
