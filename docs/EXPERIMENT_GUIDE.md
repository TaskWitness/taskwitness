**简体中文** · [English](EXPERIMENT_GUIDE.en.md)

# 实验指南：从真实设备到可信的结果

这是第 8–30 天实验（手机 + 称重传感器，至少 200 次独立标注的放置尝试）的操作规程。每一步使用的命令现在都已实现。硬件说明见 [hardware/README.md](../hardware/README.md)。

```
记录日志 ─► 校准 ─► 视频跟踪 ─► 生成 episode ─► 标注 ─► 验证 / 评估 / 估计
```

## 动手搭建之前：先用仿真器演练

```bash
taskwitness simulate place --n 500 --preset lab --set load_noise_g=1.0 --out sim
taskwitness evaluate sim --by failure_mode --order-by trial
```

它按你预期的噪声水平生成带已知真值的回合，让你在采集真实数据之前就能看到：做出判定需要多少次试验、哪些失败类型会落入 UNKNOWN、采样率和阈值是否够用。其失败类型和噪声水平都是假设，见 [SIMULATION.md](SIMULATION.md)。不要把仿真器的数字当作结果。

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

输出会给出噪声、残差和 `suggested_place_config`。如果最大误差超过几克，先修正机械结构（板要刚性、线缆不要受力）再继续。

然后用已知正常的录像来设定 Oracle 阈值，而不是靠猜。分别记录空称重板和物体静置在板上的状态，最好分多次、多个时段采集（默认 α = 0.05 时，每类至少需要 19 个 1 秒窗口；记录一分钟约得到 59 个）：

```bash
taskwitness calibrate thresholds --empty empty.csv --object 52=block.csv \
    --load-cell-cal loadcell.cal.json --alpha 0.05 --out thresholds.json
```

只要设备在校准与实验之间没有漂移，新的正常窗口超出每个阈值的概率就不超过 α。现在就把输出中的 `config` 部分写入 `config.json`，不要等看到结果之后再改。

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
- 成对误判通过的 McNemar p 值；如果想提前停止，可以用序贯检验：`taskwitness evaluate ... --order-by trial` 按试验顺序读取回合（导入时用 `--tag trial=N` 设置数值标签），报告是否以及在第几个不一致对处拒绝“没有差异”，无论查看多少次，第一类错误率都保持在 α 以内。顺序和 α 要在第 0 步确定，不能事后再定；
- `config_sha256` 与证据摘要列表。

`estimate` 会打印多个有效区间（仅用标签、预测增强，渐近与有限样本各一种）。请在第 0 步决定报告哪一个：看到结果后再选最窄的一个，会使其覆盖率保证失效。预测增强区间只有在判定器很准确且有数千个回合时才有帮助；在小规模实验里，只用标签通常更窄。

无论结果对 TaskWitness 有利与否，都要公开。

## 8. 在同一批回合上审计其他判定器

把任意判定器的逐回合分数（Robometer 成功概率、TOPReward、VLM 的判定）导出为 `episode_id,score`，然后运行：

```bash
taskwitness audit --judge robometer.csv --episodes episodes --by failure_mode --out audit.json
```

可以得到它相对于你的标签的误判通过、平衡准确率、ROC-AUC、校准误差和成功偏差，以及与 TaskWitness 的成对比较。

## 如果你的试验已经在 LeRobot 数据集中

可以不做第 3 到 5 步，而是把数据集的列映射成传感器数据流，然后转换（需要 `pip install "taskwitness[lerobot]"`，以及数据集的 `meta/` 和 `data/` 目录；不会读取视频）：

```bash
taskwitness lerobot path/to/dataset --mapping mapping.json --out episodes
```

映射文件指定哪些列成为 `load_cell`、`gripper_width`、`button` 或 `gripper`，可选的 `segments` 列（把一段长录像按动作拆成多个 episode）、人工标签列，以及任务文本过滤。REASSEMBLE 的完整示例在 `examples/lerobot/reassemble_pick_mapping.json`（其中物体宽度区间只是占位值：请填入你的物体的真实区间，或像 `examples/real_data/reassemble_grasp.py` 那样按物体分别设定）；字段说明在 `taskwitness.integrations.lerobot` 模块的文档字符串中。每个 episode 都记录其来源数据文件的 SHA-256。若要在拼接的相机视频里跟踪某个回合那一段中的物体，用 `taskwitness track VIDEO --start-s S --end-s E`，时间段取自 `LeRobotDataset.video_span` 的返回值。

## 9. 可选：为证据包签名

```bash
taskwitness keygen --dir keys
taskwitness verify episodes/trial-001.json --out bundles/trial-001.json
taskwitness sign bundles/trial-001.json --key keys/taskwitness.key --out bundles/trial-001.sig.json
taskwitness verify-signature bundles/trial-001.json bundles/trial-001.sig.json --public-key keys/taskwitness.pub
```

签名能证明证据包出自你的密钥且未被修改，但不能证明判定正确。
