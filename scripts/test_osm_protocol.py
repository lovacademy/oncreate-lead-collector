"""Prevent failures when the signed collector requests free-source checkpoints."""
import json
import unittest
from unittest.mock import patch
import daily_lead_discovery as collector

class CollectorProtocolTests(unittest.TestCase):
    def test_osm_commands_are_supported(self):
        class Fake:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,*args):return json.dumps({"ok":True,"city":None}).encode()
        with patch.object(collector,"INGEST_URL","https://example.org/ingest"), \
             patch.object(collector,"TOKEN","test-placeholder-token"), \
             patch.object(collector,"github_oidc_token",return_value="signed-test-job"), \
             patch.object(collector.request,"urlopen",return_value=Fake()) as opened:
            for command in ("geo_osm_next","geo_osm_mark"):
                result=collector.pg("collection_control",{
                    "action":command,"job_id":"00000000-0000-0000-0000-000000000000"
                })
                self.assertTrue(result["ok"])
                request=opened.call_args.args[0]
                self.assertIn(command,request.data.decode())

if __name__=="__main__":
    unittest.main()
