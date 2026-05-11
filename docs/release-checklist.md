# Release checklist

- [ ] Run `python -m compileall src tools tests`
- [ ] Run `python tools/verify_no_secrets.py`
- [ ] Run `python -m unittest discover -s tests`
- [ ] Confirm no `secrets.env`, state JSON, logs, or real keys are committed
- [ ] Tag release, e.g. `v0.2.0`
