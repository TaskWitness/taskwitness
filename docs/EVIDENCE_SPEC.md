**简体中文** · [English](EVIDENCE_SPEC.en.md)

# 证据规范（v0）

两种 JSON 文档：**episode**（输入）和**证据包**（输出）。两者都由 `schema` 字段标注版本。在 v1 之前，v0 可能不经通知就发生变化。

## Episode：`taskwitness.episode/v0`

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
  "label": {"verdict": "PASS", "note": "独立人工标注"}
}
```

| 字段 | 是否必需 | 说明 |
| --- | --- | --- |
| `schema`、`episode_id`、`task` | 是 | 使用 `PlaceOracle` 时，`task.type` 必须为 `place`。 |
| `task.object.mass_g` | 是 | 正数，用于与称重读数比对。 |
| `task.target_zone` | 是 | 与 `video[].object_xy` 同一坐标系下的轴对齐矩形（样例中单位为米）。假定称重传感器正好位于该区域下方。 |
| `claim` | 否 | 机器人自报的结果，从不用于判定。 |
| `video` | 否 | 预先计算好的物体位置，置信度范围 [0, 1]。 |
| `sensors.load_cell` | 否* | 目标称重板上的重量（克）。*没有它时，判定永远是 UNKNOWN。 |
| `sensors.gripper` | 否 | `open` / `closed`。 |
| `label` | 否 | 用于评测的真值。判定前被剔除，也不计入 `evidence_sha256`。 |

时间戳 `t` 的单位是秒，且各数据流使用同一时钟。回合在所有数据流中最晚的时间戳处结束。允许存在额外字段，它们也会被证据摘要覆盖。

## 证据包：`taskwitness.evidence/v0`

| 字段 | 含义 |
| --- | --- |
| `verdict` | `PASS`、`FAIL` 或 `UNKNOWN`。 |
| `reasons` | 按顺序排列的可读理由，第一条是结论摘要。 |
| `claim.robot_claimed_success` | 从 episode 复制而来。 |
| `claim.contradicted` | 自报为 `true` 而判定为 FAIL，或自报为 `false` 而判定为 PASS 时为 true。 |
| `comparison.vision_only_verdict` | 仅使用视频 Oracle 的判定者会给出的结论。用于分析，不参与判定。 |
| `oracles[]` | 每个 Oracle 的 `state`、`detail` 和原始 `measurements`（窗口、均值、标准差、比例等）。 |
| `timeline[]` | 关键事件：夹爪张开、称重上升/下降、最后一个传感器样本。 |
| `config` | 使用的所有阈值。 |
| `integrity.evidence_sha256` | 去掉 `label` 后的 episode 规范化 JSON 的 SHA-256。 |
| `integrity.bundle_sha256` | 去掉该字段后的证据包规范化 JSON 的 SHA-256。 |

规范化 JSON：键排序，分隔符为 `,` 和 `:`，UTF-8 编码，无多余空白。

`taskwitness check bundle.json --episode episode.json` 会重新计算两个摘要。摘要能发现意外或简单的改动，但它不是签名：任何人都能重新计算，因此无法证明证据包由谁生成。带签名的证据包属于未来工作。
