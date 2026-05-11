# Contributing

Before opening a PR:

```bash
python -m compileall src tools tests
python tools/verify_no_secrets.py
python -m unittest discover -s tests
```

Do not add account creation, payment automation, dashboard scraping, or provider-rule evasion.
