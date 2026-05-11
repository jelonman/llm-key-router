import tempfile, unittest
from pathlib import Path
from llm_key_router.app import State

class StateTests(unittest.TestCase):
    def test_state(self):
        with tempfile.TemporaryDirectory() as d:
            s=State(Path(d)/"s.json")
            s.inc_request("p","k")
            self.assertEqual(s.daily_count("p","k"),1)
            s.block_model("p","m",5,"rate","up")
            self.assertTrue(s.model_blocked("p","m","up"))

if __name__=="__main__": unittest.main()
