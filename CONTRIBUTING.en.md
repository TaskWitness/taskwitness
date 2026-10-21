[简体中文](CONTRIBUTING.md) · **English**

# Contributing

Thanks for helping check reality.

## Most wanted

1. **Real experiments**, collected with the [experiment guide](docs/EXPERIMENT_GUIDE.en.md). Labeled place attempts with load-cell data in the
   [episode format](docs/EVIDENCE_SPEC.en.md). Failures of TaskWitness are as
   valuable as successes; please include them.
2. **Reproductions** on your own rig, with the config you used.
3. **Bug reports** with the episode file that triggers the problem.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'          # core only; optional-feature tests are skipped
pip install -e '.[dev,all]'      # with video, signing and Inspect Robots
pytest -q
```

If you change `examples/synthetic/generate.py` or
`examples/synthetic_button/generate.py`, run it to regenerate the episodes and
commit the JSON files; CI checks they are in sync.

The core modules (everything except `vision`, `signing` and `integrations`)
must stay free of third-party dependencies.

## Ground rules

- Do not describe planned features as existing ones in docs or READMEs.
- Keep synthetic data clearly marked as synthetic.
- Verdict logic changes need a test showing the case they fix.
