<div align="center">

# 🔍 TaskWitness

### 超越视觉的物理证据

**不要轻信机器人的自我报告，去验证真实发生了什么。**

[![CI](https://github.com/TaskWitness/taskwitness/actions/workflows/ci.yml/badge.svg)](https://github.com/TaskWitness/taskwitness/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](pyproject.toml)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

**简体中文** · [English](README.en.md)

[快速开始](#-3-分钟体验) · [工作原理](#️-工作原理) · [路线图](#️-路线图) · [参与贡献](#-参与贡献)

<img src="docs/assets/demo.zh.svg" alt="合成样例：视频显示积木在目标区内（PASS），称重数据显示称重板为空（FAIL）" width="860">

<sub>图中为合成样例 <code>03_bounced_off</code>，由 <code>examples/synthetic</code> 中的数据绘制，并非真实机器人测量结果。</sub>

</div>

---

## 💡 为什么需要 TaskWitness？

机器人策略、VLA 和视觉成功检测器越来越频繁地报告“任务完成”。但相机会被骗：夹爪其实没松开、物体弹出了目标区、跟踪器停在了最后一帧。

**TaskWitness 是面向 Physical AI 的独立结果验证层。** 它独立于机器人策略，以物理传感器证据为主、视频为辅，给出可审计的判定。

| | 纯视觉判定 | **TaskWitness** |
| --- | --- | --- |
| 主要依据 | 画面 | **物理传感器** |
| 采信机器人自报结果？ | 常常 | **从不** |
| 证据不足时 | 猜测 | **明确输出 `UNKNOWN`** |
| 输出 | 一个分数 | **判定 + 证据包** |
| 可复现、防篡改 | 很少 | **是（SHA-256）** |

> TaskWitness **不负责**机器人控制、不训练策略，也不取代 LeRobot、ROS 2 等评测框架，而是作为外部结果判定器接入它们。

---

## 🚀 3 分钟体验

不需要机器人，不需要 GPU，除 Python 3.10+ 外零依赖。

```bash
git clone https://github.com/TaskWitness/taskwitness
cd taskwitness
python -m venv .venv
source .venv/bin/activate        # Windows：.venv\Scripts\activate
pip install -e .

taskwitness batch examples/synthetic --out report.json
```

```text
PASS     01_clean_success.json  (stable load on the target plate matches the object's mass)
FAIL     02_not_released.json  (only part of the object's weight is on the plate while the gripper is still closed: object not released)
FAIL     03_bounced_off.json  (load cell shows the target plate is empty at end of episode)
UNKNOWN  04_sensor_dropout.json  (no usable load-cell evidence; refusing to judge from video alone)
UNKNOWN  05_evidence_conflict.json  (load matches the object but video places it outside the zone; evidence conflict)
5 episodes: 1 PASS, 2 FAIL, 2 UNKNOWN; 0/5 labeled episodes disagree with their label
```

| 样例 | 场景 | 纯视觉 | TaskWitness |
| --- | --- | --- | --- |
| 01 | 正常放下并松开夹爪 | PASS | **PASS** |
| 02 | 积木碰到称重板，但夹爪始终没有松开 | PASS | **FAIL** |
| 03 | 积木落下后弹到夹具后面，视频跟踪器卡在目标区 | PASS | **FAIL** |
| 04 | 放置前称重数据流中断 | PASS | **UNKNOWN** |
| 05 | 称重正确，但相机看到积木在目标区外 | FAIL | **UNKNOWN** |

👉 在 **02** 和 **03** 中，纯视觉判定为 **PASS**，物理证据显示 **FAIL**。

验证单个样例并检查证据包：

```bash
taskwitness verify examples/synthetic/02_not_released.json --out bundle.json
taskwitness check bundle.json --episode examples/synthetic/02_not_released.json
```

| 退出码 | `0` | `1` | `2` | `3` |
| --- | --- | --- | --- | --- |
| 含义 | PASS | FAIL | UNKNOWN | 输入错误 |

可直接用于 CI 或评测循环。

---

## ⚙️ 工作原理

```text
 机器人 / VLA / 智能体 ──► 动作 · 视频 · 自报“成功”
                                │
                        TaskWitness Core
       ┌───────────────┬────────┴────────┬────────────────┐
    称重证据          夹爪状态          视频证据        （更多 Oracle）
       └───────────────┴────────┬────────┴────────────────┘
                             证据融合
                                │
             PASS / FAIL / UNKNOWN  +  证据包
        时间线 · 测量数据 · 判定理由 · 阈值配置 · SHA-256 摘要
```

**三条原则**

1. 🏋️ **物理优先。** 目标区下方的称重传感器是主要依据；视频只能否决 PASS，不能单独产生 PASS。
2. ❓ **UNKNOWN 是功能。** 证据缺失、读数未稳定或证据冲突时，拒绝猜测。
3. 🙈 **不看自报与标签。** 机器人自报结果和人工标签在判定前被剔除，仅在判定后用于对照。

<details>
<summary><b>PlaceOracle 完整判定表</b></summary>

| 称重（最终稳定窗口） | 夹爪 | 视频 | 判定 |
| --- | --- | --- | --- |
| 无数据或样本不足 | 任意 | 任意 | UNKNOWN |
| 读数未稳定 | 任意 | 任意 | UNKNOWN |
| 超过物体重量 | 任意 | 任意 | UNKNOWN |
| 空载 | 任意 | 任意 | **FAIL** |
| 部分重量 | 闭合 | 任意 | **FAIL**（未释放） |
| 部分重量 | 张开 / 未知 | 任意 | UNKNOWN |
| 与物体重量一致 | 任意 | 在目标区外 | UNKNOWN（证据冲突） |
| 与物体重量一致 | 闭合 | 在目标区内 / 无数据 | UNKNOWN（可能在按压） |
| 与物体重量一致 | 张开 / 未知 | 在目标区内 / 无数据 | **PASS** |

所有阈值定义在 `PlaceOracleConfig` 中，并完整写入每个证据包。

</details>

📄 数据格式：[docs/EVIDENCE_SPEC.md](docs/EVIDENCE_SPEC.md) · 🏗️ 架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 📦 当前状态：v0.1

**如实说明：pre-alpha。** 仓库中的样例全部为合成数据，尚无真实机器人、相机或称重传感器的测量结果。

| ✅ 已实现 | 🛠️ 尚未实现 |
| --- | --- |
| `PlaceOracle`：物体放置验证 | 从原始视频推断物体位置 |
| 称重 + 夹爪 + 视频的证据融合，显式输出 `UNKNOWN` | 传感器驱动与硬件适配器 |
| 确定性、可防篡改的证据包 | 校准工具 |
| 命令行：`verify` · `batch` · `check` | LeRobot 等评测框架插件 |
| 5 组合成样例、自动化测试与 CI | `ButtonPressOracle`（计划 v0.2） |

---

## 🗺️ 路线图

| 阶段 | 重点 | 验收 |
| --- | --- | --- |
| **D1–7** | 合成演示、命令行、测试 ✅；公开视频人工标注 | 陌生开发者独立跑通；≥5 位目标开发者反馈 |
| **D8–30** | 手机 + 称重传感器，≥200 次独立标注实验 | 预设条件下，融合方案能否显著降低误判通过 |
| **D31–60** | WitnessNode 传感器盒、一个评测框架插件、社区机器人（如 SO-101） | ≥2 个外部真实机器人环境运行实验 |
| **D61–90** | 公开真实实验结果，发布 WitnessBench 首版 | ≥1 份外部独立复现 |

详情：[docs/ROADMAP_90_DAYS.md](docs/ROADMAP_90_DAYS.md) · 硬件说明：[hardware/README.md](hardware/README.md)

---

## 🧩 项目家族

| 名称 | 内容 | 状态 |
| --- | --- | --- |
| **TaskWitness Core** | 开源验证 SDK | v0.1（本仓库） |
| **WitnessNode** | 低成本传感器盒 | 设计草案 |
| **WitnessKit** | 真实物理实验工具包 | 规划中 |
| **WitnessBench** | 社区测试数据集 | 规划中 |

**真正的开源：** 采用 Apache-2.0。Oracle、传感器方案、融合算法、本地报告、证据导出和 UNKNOWN 逻辑现在开源，将来也保持开源。

---

## 🤝 参与贡献

现在最有价值的贡献是**一次真实实验**：带称重数据和人工标签的放置任务记录，**尤其是** TaskWitness 判错的案例。

有机械臂、称重传感器，甚至只有手机和厨房秤？欢迎提 Issue。

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

<div align="center">

**当 AI 说“成功”时，谁来核实现实？**

<sub>基于 <a href="LICENSE">Apache-2.0</a> 许可证发布。</sub>

</div>
