**简体中文** · [English](EXPERIMENT_GUIDE.en.md)

# 实验指南：从真实设备到可信的结果

这是第 8–30 天实验（手机 + 称重传感器，至少 200 次独立标注的放置尝试）的操作规程。每一步使用的命令现在都已实现。硬件说明见 [hardware/README.md](../hardware/README.md)。

```
记录日志 ─► 校准 ─► 视频跟踪 ─► 生成 episode ─► 标注 ─► 验证 / 评估 / 估计
```

## 0. 采集数据前先冻结方案

在第一次试验*之前*写下并提交到 git：

- 任务（物体、质量、目标区），保存为 `task.json`；
- Oracle 阈值，保存为 `config.json`。它的 SHA-256 会以 `config_sha256` 出现在每份报告里，读者可以据此确认你没有根据结果调阈值；
- 计划制造的失败类型（例如 `none`、`not_released`、`bounce`、`edge`、`occluded`）以及每类的次数；
- 主要指标：TaskWitness 与纯视觉的条件漏判率（真实失败中被判为通过的比例），用精确 McNemar 检验比较。

```json
{"place": {"settle_window_s": 1.0, "min_settle_samples": 5, "stability_std_g": 2.0}}
```

## 1. 校准称重传感器

先在空板状态下记录 10–20 秒原始读数，再分别放上至少两个标准质量块记录。日志格式为每行 `t_ms,raw`，任何串口记录工具都能生成。

```bash
taskwitness calibrate load-cell --empty empty.csv \
    --ref 100=ref100.csv --ref 500=ref500.csv --out loadcell.cal.json
```

输出会给出噪声、残差和 `suggested_place_config`。如果最大误差超过几克，先修正机械结构（板要刚性、线缆不要受力）再继续。现在就把选定的阈值写入 `config.json`，不要等看到结果之后再改。

## 2. 校准相机

在称重板上标出至少四个点（四个角即可），在同一帧画面中读出它们的像素坐标，并在称重板坐标系中测量它们的位置，单位与 `target_zone` 一致：

```json
[{"pixel": [102, 88], "plate": [0.0, 0.0]}, {"pixel": [538, 95], "plate": [0.3, 0.0]},
 {"pixel": [551, 410], "plate": [0.3, 0.2]}, {"pixel": [95, 402], "plate": [0.0, 0.2]}]
```

```bash
taskwitness calibrate camera --points points.json --out camera.cal.json
```

重投影误差以称重板坐标单位表示，应明显小于目标区尺寸。

## 3. 记录每次试验

- 每次试验开始时做一次**同步轻敲**：在相机能看到的位置轻敲称重板。称重尖峰与视频中轻敲的那一帧给出视频与传感器之间的时钟偏移（`--video-offset-s`）。
- 在同一时钟下记录称重（`t_ms,raw`），如有条件也记录夹爪（`t_ms,open|closed`）。
- 用恒定帧率录像（必要时对手机视频重新编码）。
- 采集期间不要查看 TaskWitness 的输出。

## 4. 在视频中跟踪物体

```bash
taskwitness track trial-001.mp4 --color 200,40,40 --tolerance 60 \
    --roi 80,60,560,420 --camera-cal camera.cal.json --out trial-001.video.json
```

用肉眼抽查几帧。在称重板周围设置感兴趣区域（ROI）能排除大部分误检。

## 5. 生成 episode

```bash
taskwitness ingest place --task task.json --id trial-001 \
    --load-cell trial-001.load.csv --load-cell-cal loadcell.cal.json \
    --gripper trial-001.gripper.csv \
    --video trial-001.video.json --video-offset-s 0.42 \
    --claim true --tag failure_mode=bounce --out episodes/trial-001.json
```

episode 会在 `provenance` 中记录每个源文件的 SHA-256，因此证据包的证据摘要覆盖了原始数据。默认严格解析；只有在同时报告跳过了多少行的情况下才使用 `--lenient`。

## 6. 独立标注

由没有执行该次试验、也看不到 TaskWitness 输出的人，通过直接检查给出 PASS 或 FAIL 标签，并用 `--label` 写入。若要使用 `estimate`，需在标注开始前选定一个**均匀随机的子集**进行标注；不要挑选“有意思”的试验。

## 7. 验证、评估、估计

```bash
taskwitness batch episodes --config config.json --out batch.json
taskwitness evaluate episodes --config config.json --by failure_mode --out eval.json
taskwitness estimate episodes --config config.json --out estimate.json
```

需要一起报告：

- TaskWitness 与纯视觉各自的条件漏判和误判失败，附 95% 区间；
- UNKNOWN 率：用很高的 UNKNOWN 率换来的低漏判率不算胜利；
- 绝对漏判、审计覆盖率，以及按失败类型的拆分；
- 成对误判通过的 McNemar p 值；
- `config_sha256` 与证据摘要列表。

无论结果对 TaskWitness 有利与否，都要公开。

## 8. 在同一批回合上审计其他判定器

把任意判定器的逐回合分数（Robometer 成功概率、TOPReward、VLM 的判定）导出为 `episode_id,score`，然后运行：

```bash
taskwitness audit --judge robometer.csv --episodes episodes --by failure_mode --out audit.json
```

可以得到它相对于你的标签的误判通过、平衡准确率、ROC-AUC、校准误差和成功偏差，以及与 TaskWitness 的成对比较。

## 9. 可选：为证据包签名

```bash
taskwitness keygen --dir keys
taskwitness verify episodes/trial-001.json --out bundles/trial-001.json
taskwitness sign bundles/trial-001.json --key keys/taskwitness.key --out bundles/trial-001.sig.json
taskwitness verify-signature bundles/trial-001.json bundles/trial-001.sig.json --public-key keys/taskwitness.pub
```

签名能证明证据包出自你的密钥且未被修改，但不能证明判定正确。
