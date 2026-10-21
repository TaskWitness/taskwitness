**简体中文** · [English](README.en.md)

# WitnessNode 硬件说明（草案）

状态：**仅为设计笔记。** 固件和接线都还没有制作或测试；主机端软件已经具备：`taskwitness calibrate` 和 `taskwitness ingest`。下面的器件选择是第 8–30 天实验的起点，而不是经过验证的物料清单。

## 目标

用最便宜的传感器方案，为 `PlaceOracle` 提供独立的物理证据：目标区下方一块刚性称重板，在与相机共享的时钟上持续报告重量。

## 第一版原型

| 部件 | 用途 | 说明 |
| --- | --- | --- |
| 条形称重传感器（1–5 kg 量程） | 测量目标称重板上的重量 | 量程尽量接近最重的测试物体，以获得更好的分辨率。 |
| HX711 24 位 ADC 模块 | 读取称重传感器 | 常见且便宜；支持 10 或 80 样本/秒。 |
| 带 USB 串口的微控制器（如 ESP32 或 Arduino 类开发板） | 输出带时间戳的读数 | 只用现成开发板；前 90 天不做定制 PCB。 |
| 刚性板（亚克力 / MDF）+ 垫片 | 定义目标区 | 标定后，板的轮廓要与 `task.target_zone` 一致。 |
| 手机或 USB 相机 | 视频证据 | 固定安装；画面中需包含称重板和可见的时钟或同步标记。 |

## 数据约定

节点每个样本输出一行，例如 `t_ms,raw`（原始 ADC 计数）。用任何串口记录工具保存为文件后：

```bash
taskwitness calibrate load-cell --empty empty.csv --ref 100=ref100.csv --ref 500=ref500.csv --out loadcell.cal.json
taskwitness ingest place --task task.json --id trial-001 --load-cell trial-001.csv --load-cell-cal loadcell.cal.json --out trial-001.json
```

格式见 [../docs/EVIDENCE_SPEC.md](../docs/EVIDENCE_SPEC.md)，完整流程见 [../docs/EXPERIMENT_GUIDE.md](../docs/EXPERIMENT_GUIDE.md)。固件与实时记录器尚未编写。

## 校准清单

1. 空板去皮，然后用至少两个标准质量块标定量程（`taskwitness calibrate load-cell`，会报告噪声、残差和建议阈值）。
2. 每批实验都记录标定用的质量块和残余误差。
3. 在空载且稳定的称重板上测量噪声（标准差）；`stability_std_g` 必须明显高于它。
4. 测量从释放物体到读数稳定所需的时间；`settle_window_s` 和回合结束时间必须留出这段时间。
5. 同步时钟：每个回合开始时在称重板上轻敲一下，让相机拍到，并把称重尖峰与视频帧对齐。

按钮任务可直接读取按钮自身的触点（例如接到微控制器的数字输入），以 `t_ms,1|0` 记录，再用 `taskwitness ingest button_press` 导入。

## 已知限制

- 单块称重板无法区分物体落在板上的*哪个位置*；板的轮廓本身就是目标区。
- 机器人底座的振动可能耦合进称重传感器，需要对称重板做隔振。
- 比默认 `empty_threshold_g` 更轻的物体（几克以内）无法被检测到。
