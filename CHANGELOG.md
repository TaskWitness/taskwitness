**简体中文** · [English](CHANGELOG.en.md)

# 更新记录

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
