**简体中文** · [English](CHANGELOG.en.md)

# 更新记录

## 0.5.0（2026-10-21）

### 新增

- **LeRobot v3 数据集适配器**：`taskwitness lerobot ROOT --mapping map.json --out DIR`（可选依赖 `[lerobot]` = pyarrow）。直接读取数据集的 parquet 文件，不需要 `lerobot` 软件包，也不读取视频；把选定的列映射成称重、夹爪宽度、按钮、夹爪状态数据流；可按列把一段长录像拆成每个动作一个 episode；读取人工标签；按任务文本前缀过滤；记录数据文件的 SHA-256。`LeRobotDataset.video_span` 给出每个回合在拼接相机视频中的片段。
- `taskwitness track --start-s --end-s` 与 `read_video(start_s, end_s)`：跟踪拼接视频中的某一段。
- 示例映射 `examples/lerobot/reassemble_pick_mapping.json`。

### 验证

- 适配器在 REASSEMBLE 的 LeRobot 移植版（149 个回合、143 万帧）上运行：得到 1,192 个抓取片段，1,092 个成功、100 个失败，与此前独立脚本完全一致。`examples/real_data/reassemble_grasp.py` 改为通过适配器读取数据，结果逐项相同（测试集 24 次失败中误判通过 2 次）。
- 测试使用按真实布局手工构建的小型 LeRobot v3 数据集（跨两个数据文件、含多片段回合），覆盖映射校验、版本检查、缺失文件、非连续回合等错误情形。

### 局限

- 一个 LeRobot 回合必须位于同一个数据文件内（LeRobot 自己的工具写出的文件都满足）；不支持 v3 以外的版本；不会把结果写回数据集。

## 0.4.0（2026-10-21）

用物理仿真和一个真实公开数据集检验 TaskWitness，并根据发现修正了 Oracle。

### 新增

- **仿真**：`taskwitness simulate place|button_press` 与 `examples/simulation/study.py`。回合由潜在的物理经过生成（含称重噪声与漂移、落地后振荡、丢样本、跟踪器卡住、时钟偏差、接触抖动），标签来自这一经过而不是任何 Oracle；故意包含 Oracle 并非为之设计的失败（例如另一个物体落在称重板上且跟踪器卡住）。结果见 [docs/SIMULATION.md](docs/SIMULATION.md)。
- **GraspOracle**（任务类型 `grasp`）：根据夹爪手指最终停在哪里、对照物体宽度区间判断抓取。
- **真实数据检验**：`examples/real_data/reassemble_grasp.py` 在 REASSEMBLE（CC-BY-4.0，Franka，人工成功标签）上，用官方训练/测试划分检验 GraspOracle。测试集 24 次真实失败中，误判通过 2 次（8.3%，区间 2.3%–25.8%），而“信任片段已结束”为 100%、不带区间的“夹爪没有完全张开”检查为 87.5%。同时如实记录：保形保证在跨会话时没有成立。见 [docs/REAL_DATA.md](docs/REAL_DATA.md)。
- `wrist_ft` 仿真设备：用 REASSEMBLE 实测的腕部力传感器噪声（中位数 11.6 g）和偏置（四分位宽度 143 g）说明为什么机器人自带的腕部传感器不能代替称重传感器。

### 变更（由仿真和真实数据发现的问题驱动）

- **PlaceOracle** 新增“回合开始时称重板必须为空”检查（`baseline_window_s`，取前 0.5 秒读数的中位数）：上一次遗留的物体或清零错误现在得到 UNKNOWN，而不是把最终重量算作本次成功。仿真（lab 设备）中误判通过从 5.5% 降到 3.3%，对正常成功没有代价。
- **ButtonPressOracle**：采样只能给出接触时长的上下界。过去按采样间隔估计时长，在 20 Hz 开关采样下 111 次轻擦中有 37 次被计为按压；现在只有确定不短于 `min_hold_s` 的接触才计为按压，无法判断的给 UNKNOWN（`UNRESOLVED_HOLD`）。另外，当存在次数上限且有一次无法排除的接触时，不再给出 PASS（该漏洞使 20 Hz 下有 1.0% 的真实失败被判通过，现为 0）。
- `calibrate thresholds` 与默认阈值的取舍被量化：在称重噪声 ≥ 2 g 时保形校准把正常成功的 UNKNOWN 从 44%（4 g 时为 100%）降到 14%（20%）；在噪声 ≤ 1 g 时校准阈值反而更严，UNKNOWN 从约 2% 升到 6%–11%。

### 说明

- 仿真的失败类型和噪声水平是作者的假设，不是测量结果。
- 没有任何公开机器人数据集记录称重传感器或按钮触点，因此称重和按钮 Oracle 仍没有真实硬件结果。

## 0.3.0（2026-10-21）

补全 v0.2 中尚未实现的统计方法。所有统计保证都有模拟检验，实测中的局限也如实写入文档。

### 新增

- **序贯检验**：`taskwitness evaluate` 增加任意时刻有效的成对比较（下注式 e-过程）。可以随时查看、随时停止，第一类错误率仍不超过 α。`--order-by TAG` 指定回合顺序，`--alpha` 指定水平。模拟中：无差异时 1,500 次运行拒绝 3.2%（上限 5%）；85/15 的真实差异总会被检出，中位数在第 10 个不一致对。
- **有限样本区间**：`taskwitness estimate` 增加 Waudby-Smith–Ramdas 下注式区间（仅用标签），以及两个下注式区间并集界的有限样本预测增强推断。
- **保形阈值校准**：`taskwitness calibrate thresholds` 用已知正常录像设定稳定性、空载、质量容差阈值，保证新的正常窗口超出阈值的概率不超过 α；样本不足时报错而不是猜测，并提示过轻的物体。
- 新模块 `inference` 与 `thresholds`，纯 Python，无新依赖。

### 说明

- 有限样本预测增强区间并不总是更窄：判定器误判通过 10%、400 个回合、40 个标签时，它比只用标签更宽（0.68 对 0.44），只有判定器很准确且有数千个回合时才占优。`estimate` 会打印全部区间并提醒事先选定要报告的一个。
- 序贯检验比 STEP 和 N-SCORE 简单，只适用于成对的二元结果。

## 0.2.0（2026-10-21）

新增功能依据近期研究设计，理由见 [docs/RESEARCH.md](docs/RESEARCH.md)。

### 新增

- **ButtonPressOracle**：以按钮自身触点为主要证据；合并接触抖动、要求最短按压时长、检测观测缺口与结束时仍按下、支持按压次数上下限；视频只能否决。新增 6 组合成样例（`examples/synthetic_button`）。
- **校准**：`taskwitness calibrate load-cell`（去皮、标定、噪声、残差、建议阈值）与 `taskwitness calibrate camera`（归一化 DLT 单应矩阵、重投影误差、退化点检测）。
- **数据导入**：`taskwitness ingest place|button_press` 把 `t_ms,value` 日志与跟踪结果转为 episode，统一时钟，记录每个源文件的 SHA-256。
- **视频跟踪**（可选 `[vision]`）：`taskwitness track`，支持感兴趣区域的颜色块跟踪基线。
- **统计工具**：
  - `taskwitness evaluate`：条件 / 绝对漏判、误判失败、UNKNOWN 率（Wilson 区间）、审计覆盖率、按标签分层、精确 McNemar 检验；
  - `taskwitness audit`：审计外部判定器（平衡准确率、ROC-AUC、ECE、成功偏差），并与 TaskWitness 成对比较；
  - `taskwitness estimate`：预测增强推断（PPI）估计成功率。
- **配置文件**：`--config` 冻结阈值，报告中记录 `config_sha256`。
- **签名**（可选 `[sign]`）：`keygen`、`sign`、`verify-signature`，Ed25519，需显式固定公钥。
- **Inspect Robots 集成**（可选 `[inspect]`）：`taskwitness` 与 `taskwitness_unknown` 两个 scorer，通过 entry point 注册，并在真实的 `inspect_robots.eval()` 流程中测试。
- Python API：`taskwitness.judge()`、`taskwitness.verify_episode()`。
- 文档：研究笔记、实验指南，所有文档提供中英文版本。

### 变更

- episode 校验更严格：拒绝 NaN 和无穷大（Python 的 JSON 解析器会接受它们），错误信息指向具体字段，例如 `sensors.load_cell[3]`。
- PlaceOracle：当物体重量无法与空板区分时输出 `UNRESOLVABLE` → UNKNOWN，而不是误判。
- `batch` 遇到单个坏文件时继续处理其余文件，并在报告中列出错误（退出码 3）。
- CI 增加仅核心依赖的测试任务，确保核心保持零依赖。

## 0.1.0（2026-10-21）

- 首个版本：PlaceOracle、证据融合、确定性证据包、命令行 `verify` / `batch` / `check`、5 组合成样例。
