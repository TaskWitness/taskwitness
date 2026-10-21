**简体中文** · [English](CONTRIBUTING.en.md)

# 参与贡献

感谢你帮助我们核实现实。

## 最需要的贡献

1. **真实实验。** 带称重数据和人工标签的放置任务记录，建议按[实验指南](docs/EXPERIMENT_GUIDE.md)采集，并按[证据规范](docs/EVIDENCE_SPEC.md)整理。TaskWitness 判错的案例与判对的案例同样有价值，请务必包含。
2. **在你自己的设备上复现**，并附上所用配置。
3. **Bug 报告**，请附上能触发问题的 episode 文件。

## 开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'          # 仅核心，可选功能的测试会自动跳过
pip install -e '.[dev,all]'      # 包含视频、签名与 Inspect Robots
pytest -q
```

如果你修改了 `examples/synthetic/generate.py` 或 `examples/synthetic_button/generate.py`，请运行对应脚本重新生成 episode 并提交 JSON 文件；CI 会检查两者是否同步。

核心模块（不含 `vision`、`signing`、`integrations`）必须保持零第三方依赖。

## 基本规则

- 不要在文档或 README 中把计划中的功能写成已有功能。
- 合成数据必须明确标注为合成。
- 修改判定逻辑时，需要附带一个展示所修复情形的测试。
