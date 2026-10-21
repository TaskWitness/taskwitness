**简体中文** · [English](ROADMAP_90_DAYS.en.md)

# TaskWitness 90 天研发路线图

起始日期：2026-10-21。原则：每个阶段都有可检查的验收条件；未完成的能力不写进 README 的“已有功能”。

## D1–7：开源启动（无硬件）

- [x] PlaceOracle、证据融合、显式 UNKNOWN
- [x] CLI（verify / batch / check）、确定性证据包、SHA-256 完整性校验
- [x] 5 组合成样例（1 PASS、2 FAIL、2 UNKNOWN）、自动化测试、GitHub CI
- [ ] 选取公开机器人操作视频，人工标注结果，初步评估纯视觉判定的误判类型
- [ ] 检查 PyPI 名称、域名与目标市场商标

**验收**：陌生开发者按 README 独立运行成功；获得至少 5 位目标开发者反馈。

## D8–30：真实实验（手机 + 称重传感器）

- [ ] 搭建 WitnessNode 原型（见 `hardware/README.md`）：称重模块 + 微控制器 + USB 串口
- [x] 传感器适配器：把串口读数写成 `taskwitness.episode/v0`（`taskwitness ingest`，v0.2）
- [x] 称重与相机校准（`taskwitness calibrate`，v0.2）
- [x] 手机录像 + 简单目标检测，输出 `object_xy` 与置信度（颜色块基线 `taskwitness track`，v0.2；尚未用真实视频验证）
- [ ] 用手移动积木模拟机器人动作，采集 ≥ 200 次实验，由独立标注者给出标签
- [ ] **事先固定**测试条件、阈值与指标，再对比：纯视觉 / 纯称重 / 融合（配置冻结与统计工具已就绪：`--config`、`taskwitness evaluate`，见 [实验指南](EXPERIMENT_GUIDE.md)）

**指标**：False Pass 率、False Fail 率、UNKNOWN 率（覆盖率）、每次实验人工时间。

**验收**：在预先确定的测试条件和覆盖率下，融合方式是否显著降低 False Pass。结果无论好坏都公开。

## D31–60：生态接入

- [ ] WitnessNode 接线图、BOM、固件开源
- [x] 一个评测框架插件，以外部结果判定器方式接入（Inspect Robots scorer，v0.2）
- [ ] LeRobot 数据集适配器（目前可导出逐回合分数后用 `taskwitness audit` 对照）
- [ ] 联系拥有 SO-101 等开源机械臂的开发者，提供复现脚本与传感器方案
- [x] `ButtonPressOracle`（v0.2）

**验收**：至少 2 个外部真实机器人测试环境愿意运行实验并反馈结果。

## D61–90：公开结果与社区复现

- [ ] 公开 D8–30 真实实验的完整数据、标签、阈值与结果（包括 TaskWitness 判错的案例）
- [ ] WitnessBench 首个版本：带称重数据与独立标签的放置任务数据集
- [ ] 汇总外部机器人环境的复现结果
- [ ] 取得可复现的真实结果后，再发布 Show HN、相关 Reddit 社区与 Hugging Face Space
- [x] 证据包签名（Ed25519，`taskwitness sign`，v0.2；签名只能证明来源，不能证明判定正确）
- [x] 任意时刻有效的序贯检验、有限样本区间与保形阈值校准（v0.3，见 [研究笔记](RESEARCH.md)；STEP / N-SCORE 的完整方法尚未实现）

**验收**：至少 1 份由外部贡献者独立复现并公开的真实实验结果。

## 90 天开源检查清单

- [ ] 融合验证在独立测试集上有明确增益（控制 UNKNOWN 率、场景难度和覆盖率）
- [ ] 至少 2 个外部真实机器人测试环境
- [ ] 至少 1 份外部独立复现结果
- [ ] 总体人工成本下降（计入夹具校准、场景重置和误报复核）

**开源冷启动指标**：实际安装人数、外部复现次数、外部贡献。Star 数只作参考。

## 明确不做

通用机器人控制、训练 VLA、自研仿真器、定制 PCB、多租户 SaaS。
