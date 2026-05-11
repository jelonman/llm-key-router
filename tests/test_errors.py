import unittest
from llm_key_router.app import classify_http_error

class ErrorTests(unittest.TestCase):
    def test_429(self):
        body=b'{"error":{"metadata":{"provider_name":"Venice","retry_after_seconds":9}}}'
        et,msg,up,ra=classify_http_error(429, body, {"Retry-After":"8"})
        self.assertEqual(et,"model_or_provider_rate_limited")
        self.assertEqual(up,"Venice")
        self.assertEqual(ra,9)
    def test_401(self):
        et,_,_,_=classify_http_error(401,b"{}",{})
        self.assertEqual(et,"key_auth_error")

if __name__=="__main__": unittest.main()
