**简体中文** · [English](EVIDENCE_SPEC.en.md)

# 证据规范（v0）

TaskWitness 读写带版本号的 JSON 文档，每种文档由 `schema` 字段标识。在 v1 之前，v0 可能不经通知就发生变化。

| Schema | 生成者 | 用途 |
| --- | --- | --- |
| `taskwitness.episode/v0` | 用户、`ingest`、各集成 | 输入：任务描述 + 证据数据流 |
| `taskwitness.evidence/v0` | `verify`、`batch` | 输出：判定 + 证据包 |
| `taskwitness.video/v0` | `track` | 逐帧的物体 / 工具位置 |
| `taskwitness.calibration/v0` | `calibrate` | 称重或相机校准 |
| `taskwitness.thresholds/v0` | `calibrate thresholds` | 保形 Oracle 阈值，以及可直接使用的 `config` 配置块 |
| `taskwitness.signature/v0` | `sign` | 证据包的 Ed25519 签名 |

## Episode：`taskwitness.episode/v0`

### 放置任务

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
  "label": {"verdict": "PASS", "note": "独立人工标注"}
}
```

### 按钮任务

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

### 抓取任务

```json
{
  "schema": "taskwitness.episode/v0",
  "episode_id": "pick-017",
  "task": {"type": "grasp", "object": {"name": "round peg 2", "width_m_min": 0.004, "width_m_max": 0.008}},
  "sensors": {"gripper_width": [{"t": 0.0, "width_m": 0.040}, {"t": 0.033, "width_m": 0.039}]}
}
```

`gripper_width` 是手指位置，单位为米。由最后 `settle_window_s`（默认 0.5 秒）决定：停在区间内为 PASS；闭合超过区间（手指之间没有东西）或比物体更宽为 FAIL；接近区间边缘（`margin_m` 以内）、手指仍在移动或样本太少为 UNKNOWN。区间可用卡尺测得，或取已知成功抓取的范围（见 [REAL_DATA.md](REAL_DATA.md)）。

### 字段

| 字段 | 是否必需 | 说明 |
| --- | --- | --- |
| `schema`、`episode_id`、`task` | 是 | `episode_id` 为非空字符串。 |
| `task.type` | 是 | `place`、`button_press` 或 `grasp`。 |
| `task.object.mass_g` | 放置任务 | 正数，用于与称重读数比对。 |
| `task.target_zone` | 放置任务 | 与 `video[].object_xy` 同一坐标系下的轴对齐矩形。假定称重传感器正好位于该区域下方。 |
| `task.button.expected_presses` | 否 | 不小于 1 的整数，默认 1。 |
| `task.button.max_presses` | 否 | 不小于 `expected_presses` 的整数；按压次数超过它判为 FAIL。 |
| `task.button.zone` | 有视频时必需 | 视频需要在此区域看到工具，才能支持按压的发生。 |
| `claim.success` | 否 | 机器人自报的结果（`true`、`false` 或 `null`），从不用于判定。 |
| `video` | 否 | 预先计算好的位置（放置任务为 `object_xy`，按钮任务为 `tool_xy`），置信度范围 [0, 1]。 |
| `sensors.load_cell` | 放置任务 | 目标称重板上的重量（克）。没有它时，放置任务的判定永远是 UNKNOWN。 |
| `sensors.gripper` | 否 | `open` / `closed`。 |
| `task.object.width_m_min`、`width_m_max` | 抓取任务 | 物体宽度区间，单位为米。 |
| `sensors.gripper_width` | 抓取任务 | `width_m`：手指位置，单位为米。没有它时，抓取任务的判定永远是 UNKNOWN。 |
| `sensors.button` | 按钮任务 | `pressed: true/false`，按钮自身的触点状态。没有它时，按钮任务的判定永远是 UNKNOWN。 |
| `tags` | 否 | 自由格式的字符串，例如 `failure_mode`；`evaluate --by` 按它分组。 |
| `provenance` | 否 | 由 `ingest` 写入：工具版本、`t0_ms`、每个源文件的 SHA-256。 |
| `label` | 否 | 用于评测的真值。判定前被剔除，也不计入 `evidence_sha256`。 |

所有数值必须是有限数：即使 Python 的 JSON 解析器接受 NaN 和无穷大，TaskWitness 也会拒绝。时间戳 `t` 的单位是秒，且使用同一时钟。允许存在额外字段，它们也会被证据摘要覆盖。

### ButtonPressOracle 如何计数

一次按压是指：在一个“未按下”样本之后开始（上升沿）、确定持续至少 `min_hold_s`、并以松开结束的一段接触。采样只能给出接触时长的上下界：它至少持续了从第一个到最后一个闭合样本的时间，至多持续了从之前一个样本到之后一个样本的时间。确定足够长则计为按压，确定太短则不计，介于两者之间为 `UNRESOLVED_HOLD`（UNKNOWN）。短于 `debounce_s` 的间隙和接触视为抖动，会被合并或忽略。在最后一个样本时触点仍闭合，说明按压没有完成（UNKNOWN）。如果看到的按压次数少于要求，且开关数据流存在长于 `max_gap_s` 的缺口（包括回合开头和结尾），结果为 UNKNOWN，而不是 FAIL。

## 证据包：`taskwitness.evidence/v0`

| 字段 | 含义 |
| --- | --- |
| `oracle` | `PlaceOracle` 或 `ButtonPressOracle`。 |
| `verdict` | `PASS`、`FAIL` 或 `UNKNOWN`。 |
| `reasons` | 按顺序排列的可读理由，第一条是结论摘要。 |
| `claim.robot_claimed_success` | 从 episode 复制而来。 |
| `claim.contradicted` | 自报为 `true` 而判定为 FAIL，或自报为 `false` 而判定为 PASS 时为 true。 |
| `comparison.vision_only_verdict` | 仅使用视频 Oracle 的判定者会给出的结论。用于分析，不参与判定。 |
| `oracles[]` | 每个 Oracle 的 `state`、`detail` 和原始 `measurements`。 |
| `timeline[]` | 关键事件：夹爪张开、称重上升/下降、按下/松开。 |
| `config` | 使用的所有阈值。 |
| `integrity.evidence_sha256` | 去掉 `label` 后的 episode 规范化 JSON 的 SHA-256。 |
| `integrity.bundle_sha256` | 去掉该字段后的证据包规范化 JSON 的 SHA-256。 |

规范化 JSON：键排序，分隔符为 `,` 和 `:`，UTF-8 编码，无多余空白。

## 配置文件

```json
{"place": {"settle_window_s": 1.0}, "button_press": {"min_hold_s": 0.05}}
```

键是任务类型；字段与 `PlaceOracleConfig`、`ButtonPressConfig` 相同。未知键、非数值和负值都会被拒绝。报告中的 `config_sha256` 是完整解析后配置的摘要。

## 传感器日志（`ingest` 与 `calibrate` 的输入）

每行一个样本，格式为 `t_ms,value`。空行和 `#` 注释会被跳过；允许一行表头。取值：称重为原始计数（配合校准）或克；夹爪为 `open|closed`；按钮为 `1|0`、`true|false` 或 `pressed|released`。

## 视频观测：`taskwitness.video/v0`

```json
{"schema": "taskwitness.video/v0", "coords": "pixel",
 "frames": [{"t": 0.0, "xy": [312.5, 220.0], "confidence": 0.93}, {"t": 0.033, "xy": null, "confidence": 0.0}]}
```

`coords` 为 `pixel` 或 `plate`。像素坐标在 `ingest` 时需要相机校准；`xy: null`（未检测到）的帧会被丢弃并计数。

## 校准：`taskwitness.calibration/v0`

包含 `load_cell`（`tare_raw`、`counts_per_gram`、`noise_std_g`、`residual_rms_g`、`max_abs_error_g`、`references`，以及 `suggested_place_config`）或 `camera`（3×3 `homography`、`rms_error`、`max_error`、`points`）。

## 签名：`taskwitness.signature/v0`

包含 `algorithm`（`ed25519`）、`bundle_sha256`、`evidence_sha256`、`key_id`（原始公钥 SHA-256 的前 16 个十六进制字符）、`public_key` 和 `signature`（base64）。签名覆盖整个证据包的规范化 JSON。`verify-signature --public-key` 固定你信任的公钥；不提供时，只检查内嵌公钥的自洽性。

摘要能发现改动；签名把证据包与密钥绑定。两者都不能证明判定正确。
