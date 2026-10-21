[简体中文](CONTRIBUTING.md) · **English**

# Contributing

Thanks for helping check reality.

## Most wanted

1. **Real experiments.** Labeled place attempts with load-cell data in the
   [episode format](docs/EVIDENCE_SPEC.en.md). Failures of TaskWitness are as
   valuable as successes; please include them.
2. **Reproductions** on your own rig, with the config you used.
3. **Bug reports** with the episode file that triggers the problem.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

If you change `examples/synthetic/generate.py`, regenerate the episodes with
`python examples/synthetic/generate.py` and commit the JSON files; CI checks
they are in sync.

## Ground rules

- Do not describe planned features as existing ones in docs or READMEs.
- Keep synthetic data clearly marked as synthetic.
- Verdict logic changes need a test showing the case they fix.
