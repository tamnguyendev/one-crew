import unittest

from onecrew.dart_scan import scan_dart
from onecrew.discovery import scan_text
from onecrew.ledger import LedgerError


class DartScanTests(unittest.TestCase):
    def test_reference_assignment_only_in_dart(self):
        data = b'  _authPassword = authPassword;\n  _tokenKey = tokenKey;\n'
        with self.assertRaises(LedgerError): scan_text(data)
        self.assertEqual(scan_dart(data), data.decode())

    def test_literals_tokens_and_binary_still_rejected(self):
        for value in ("password = 'long-fixture-value';", '"password": "long-fixture-value"',
                      'password = apikey_' + 'x' * 20 + ';', 'text\0binary',
                      '-----BEGIN PRIVATE KEY', "password = 'long-fixture-value';\n_secret = secret;"):
            with self.subTest(value=value), self.assertRaises(LedgerError): scan_dart(value.encode())
        with self.assertRaises(LedgerError): scan_dart(b'\xff')

    def test_comment_and_string_content_is_not_code(self):
        statement = '\nPASSWORD = bareSecretValue;\n'
        for source in ('/*' + statement + '*/', '/* /* nested */' + statement + '*/',
                       '"""' + statement + '"""', "r'''" + statement + "'''",
                       '"unterminated' + statement):
            with self.subTest(source=source), self.assertRaises(LedgerError): scan_dart(source.encode())

    def test_comment_and_escaped_string_before_reference(self):
        data = b'// docs\nvar text = "escaped\\\" quote";\n_authPassword = authPassword;\n'
        self.assertEqual(scan_dart(data), data.decode())


if __name__ == '__main__': unittest.main()
