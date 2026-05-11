import tempfile, unittest
from pathlib import Path
from llm_key_router.app import parse_env

class ConfigTests(unittest.TestCase):
    def test_env(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"e.env"; p.write_text("A=1\nB=\"two\"\n", encoding="utf-8")
            self.assertEqual(parse_env(p), {"A":"1","B":"two"})

if __name__=="__main__": unittest.main()
