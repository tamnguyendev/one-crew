import io
import json
import os
import unittest
from unittest.mock import patch
from onecrew.jev import probe,protect,NoRedirect,JevError,main

KEY='synthetic-test-credential-only'
class Response(io.BytesIO): pass
class Client:
    def __init__(self,result): self.result=result; self.calls=0
    def open(self,request,timeout):
        self.calls+=1
        assert request.full_url=='https://api.typesafe.ai/v1/systemone'
        assert request.get_header('Authorization')=='Bearer '+KEY
        assert timeout==15
        assert KEY.encode() not in request.data
        return Response(json.dumps(self.result).encode())

class JevTests(unittest.TestCase):
    def response(self):return {'model':'jev-1.13.0','answers':{'security_change':{'type':'noul','noul':0.01}},'usage':{'input_tokens':80}}
    def test_probe_has_no_dispatch_and_one_call(self):
        client=Client(self.response()); result=probe(KEY,client)
        self.assertEqual(client.calls,1); self.assertFalse(result['dispatch_enabled'])
        self.assertIsNone(result['usage']['output_tokens']); self.assertNotIn(KEY,json.dumps(result))
    def test_invalid_probability_refused(self):
        for value in (True,float('nan'),-1,1.1,'yes'):
            result=self.response(); result['answers']['security_change']['noul']=value
            with self.assertRaises(JevError):probe(KEY,Client(result))
    def test_redirect_refused(self):
        with self.assertRaises(JevError):NoRedirect().redirect_request(None,None,None,None,None,None)
    def test_provider_exception_never_exposes_credential_or_retries(self):
        client=Client(None)
        with patch.object(client,'open',side_effect=RuntimeError(KEY)) as call:
            with self.assertRaises(JevError) as error:probe(KEY,client)
            self.assertNotIn(KEY,str(error.exception)); self.assertEqual(call.call_count,1)
    def test_cli_error_is_redacted(self):
        with patch('onecrew.jev.probe',side_effect=JevError(KEY)),patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(['doctor']),2); self.assertNotIn(KEY,output.getvalue())
    @unittest.skipUnless(os.name=='nt','DPAPI requires Windows')
    def test_real_dpapi_roundtrip(self):
        encrypted=protect(KEY.encode()); self.assertNotIn(KEY.encode(),encrypted)
        self.assertEqual(protect(encrypted,decrypt=True),KEY.encode())

if __name__=='__main__':unittest.main()
