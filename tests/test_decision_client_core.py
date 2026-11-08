"""Shared Jev boundary: no real credential store or HTTP service used."""
import copy
import io
import json
import unittest
from unittest.mock import patch

from onecrew import decision_client_core as core

KEY = 'synthetic-test-credential-only'


class RawClient:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def open(self, request, timeout):
        self.calls += 1
        return io.BytesIO(self.data)


class BoundaryTests(unittest.TestCase):
    def response(self):
        return {'model': 'jev-test', 'answers': {'test': {'type': 'choice', 'choice': 'a', 'confidence': .9,
                'probabilities': {'a': .9, 'abstain': .1}}}, 'usage': {'input_tokens': 1, 'output_tokens': 2}}

    def test_transport_limits_and_secret_echo_are_redacted_one_attempt(self):
        for data in (b'x' * 65537, b'[]', b'{"oops":', json.dumps({'model': KEY}).encode()):
            client = RawClient(data)
            with self.assertRaises(core.JevError) as caught:
                core.request_json({'safe': 'request'}, key=KEY, opener=client)
            self.assertEqual(client.calls, 1)
            self.assertEqual(caught.exception.calls, 1)
            self.assertNotIn(KEY, str(caught.exception))

    def test_invalid_or_large_request_never_reads_key_or_calls(self):
        for payload in ({'x': 'a' * 16000}, {'x': float('nan')}, {'x': object()}):
            client = RawClient(b'{}')
            with patch.object(core, 'load_key', side_effect=AssertionError('key must not be read')):
                with self.assertRaises(core.JevError) as caught:
                    core.request_json(payload, opener=client)
            self.assertEqual(caught.exception.calls, 0)
            self.assertEqual(client.calls, 0)

    def test_choice_validator_rejects_schema_probability_and_model_errors(self):
        for field, value in (('choice', 'invented'), ('confidence', True), ('confidence', float('nan')),
                             ('probabilities', {'a': 1}), ('probabilities', {'a': .1, 'abstain': .9}),
                             ('probabilities', {'a': .7, 'abstain': .7})):
            response = self.response()
            response['answers']['test'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(core.JevError):
                core.parse_choice(response, 'test', ('a', 'abstain'))
        for field, value in (('model', KEY), ('usage', [])):
            response = self.response()
            response[field] = value
            with self.assertRaises(core.JevError) as caught:
                core.parse_choice(response, 'test', ('a', 'abstain'))
            self.assertNotIn(KEY, str(caught.exception))

    def test_safe_usage_only_and_input_not_mutated(self):
        response = self.response()
        response['usage'] = {'input_tokens': True, 'output_tokens': -1, 'arbitrary': KEY}
        before = copy.deepcopy(response)
        out = core.parse_choice(response, 'test', ('a', 'abstain'))
        self.assertEqual(out['usage'], {'input_tokens': None, 'output_tokens': None})
        self.assertNotIn(KEY, json.dumps(out))
        self.assertEqual(response, before)

    def test_default_transport_uses_redirect_refusal_handler(self):
        client = RawClient(b'{}')
        with patch.object(core.urllib.request, 'build_opener', return_value=client) as build:
            core.request_json({}, key=KEY)
        self.assertIsInstance(build.call_args.args[0], core.NoRedirect)
        with self.assertRaises(core.JevError):
            build.call_args.args[0].redirect_request(None, None, None, None, None, None)


if __name__ == '__main__':
    unittest.main()
