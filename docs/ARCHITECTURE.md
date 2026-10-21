**简体中文** · [English](ARCHITECTURE.en.md)

# 架构

## 在技术栈中的位置

```
┌──────────────────────────────────────────────┐
│ 机器人 / VLA 策略 / 智能体                      │  控制机械臂、录制视频，
│（LeRobot、ROS 2、Inspect Robots、厂商软件栈）   │  可能自报“成功”
└──────────────┬───────────────────────────────┘
               │ episode：任务描述 + 传感器数据流 + 视频观测
┌──────────────▼───────────────────────────────┐
│ TaskWitness Core                              │
│  Oracle ─► 证据融合 ─► 判定 + 证据             │
└──────────────┬───────────────────────────────┘
               │ PASS / FAIL / UNKNOWN + 证据包
┌──────────────▼───────────────────────────────┐
│ 评测框架、CI、统计分析、人工复核                │
└──────────────────────────────────────────────┘
```

TaskWitness 刻意独立于被测策略：它不接触策略内部状态，不发送任何控制命令，判定时也忽略策略自报的成功结果。

## 数据流（v0.4）

```
原始日志 ──calibrate──► 校准文件
   │                         │
   ├── 视频 ──track──► taskwitness.video/v0 ──┐
   │                                          ▼
   └────────────────────ingest──────────► taskwitness.episode/v0
                                              │
                                verify / batch│（PlaceOracle、ButtonPressOracle）
                                              ▼
                                  taskwitness.evidence/v0 ──sign──► 签名
                                              │
                         evaluate / audit / estimate ──► 统计报告
```

## 模块

| 模块 | 职责 |
| --- | --- |
| `core` | 判定结果、错误类型、严格的 episode 校验（有限数值、数据流结构）、证据包组装与完整性摘要。 |
| `oracle` | `PlaceOracle`：称重最终状态（`PLACED`、`ABSENT`、`PARTIAL_LOAD`、`OVERLOAD`、`UNSTABLE`、`NO_DATA`、`UNRESOLVABLE`）、夹爪状态、视频位置，以及融合规则。 |
| `grasp` | `GraspOracle`：根据夹爪手指最终停在哪里，对照物体的宽度区间判断抓取；接近区间边缘或手指仍在移动时输出 UNKNOWN。使用机器人自身的夹爪位置，因此独立于策略自报结果，但不是外部传感器。 |
| `simulation` | 带已知真值的物理仿真（放置、按钮），噪声、掉线、跟踪器失效、时钟偏差均可调。标签来自潜在的真实经过，从不来自任何 Oracle。 |
| `button` | `ButtonPressOracle`：接触段的抖动合并与最短按压时长、观测缺口、结束时仍按下、按压次数限制；视频只能否决。 |
| `api` | `verify_episode` 按 `task.type` 分发；`judge` 返回 `Verdict`。 |
| `config` | Oracle 配置文件，严格校验；其摘要写入报告。 |
| `calibration` | 称重传感器去皮与标定（含噪声与残差）；相机单应矩阵（归一化 DLT，含重投影误差）。纯 Python。 |
| `adapters` | 把 `t_ms,value` 日志和跟踪器输出转为 episode；严格解析、时钟对齐、来源摘要。 |
| `vision` | 可选（`[vision]`）：支持感兴趣区域的颜色块跟踪器；假定恒定帧率的视频读取。 |
| `evaluate` | Wilson 区间、精确 McNemar 检验、序贯成对比较、按分层的绝对/条件漏判与审计覆盖率、外部判定器审计（AUC、ECE、成功偏差）、成功率估计。 |
| `inference` | 任意时刻有效的序贯检验（下注式 e-过程）、Waudby-Smith–Ramdas 区间、有限样本预测增强推断、分裂保形上界。纯 Python；统计保证由测试中的模拟检验。 |
| `thresholds` | 用已知正常的录像对 PlaceOracle 阈值做保形校准。 |
| `signing` | 可选（`[sign]`）：对证据包做 Ed25519 签名，需显式固定公钥。 |
| `integrations.lerobot` | 用 pyarrow 读取本地 LeRobot v3 数据集（可选 `[lerobot]`），把选定的列转成 TaskWitness episode，按片段拆分，带上人工标签和数据文件的 SHA-256 来源记录；还能给出每个回合在拼接相机视频中的片段。已在 REASSEMBLE 上验证。 |
| `integrations.inspect_robots` | 为 Inspect Robots 提供 `taskwitness` 和 `taskwitness_unknown` 两个 scorer，通过 entry point 注册。 |
| `cli` | 全部命令行命令。 |

核心部分（`core`、各 Oracle、`api`、`config`、`calibration`、`adapters`、`evaluate`、`inference`、`thresholds`）没有任何第三方依赖。

## 设计原则

1. **物理证据优先。** 视频可以否决 PASS，但不能单独产生 PASS。
2. **UNKNOWN 是功能。** 证据缺失、未稳定、未被观测或相互矛盾时输出 UNKNOWN。每个准确率数字旁边都报告 UNKNOWN 率。
3. **证据与标签分离。** 标签和机器人自报结果在任何 Oracle 运行之前就被剔除。
4. **确定性。** 相同输入 + 相同配置 + 相同版本，得到逐字节相同的证据包，因此证据包可以对比、缓存，并由第三方重新验证。
5. **没有隐藏阈值。** 完整配置写入每个证据包；配置文件的摘要写入每份报告。
6. **先统计，后结论。** 比率附带区间；判定器之间的比较是在同一批回合上的成对检验。

## 尚未实现

以下是方向，不是功能。

- WitnessNode 固件与实时串口记录器（目前：任何能写出 `t_ms,value` 的记录工具即可）。
- 把结果写回 LeRobot 数据集，以及读取非 v3 版本的 LeRobot 数据集。
- 基于学习或 VLM 的视频检测器（目前：颜色块基线）。
- STEP 的精确停止规则、N-SCORE 的部分得分指标、SureSim 的真实/仿真成对修正项（目前：针对成对二元结果的较简单序贯检验）。

这些取舍背后的理由见 [RESEARCH.md](RESEARCH.md)。
