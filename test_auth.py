"""OAuth paths use fake credentials and fake Gmail only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from app import connect_gmail, SCOPES


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = patch('app.PRIVATE', self.root)
        self.private.start()
        self.addCleanup(self.private.stop)
        self.credentials = Mock(valid=True, expired=False)
        self.credentials.to_json.return_value = '{"fake":"test"}'

    def test_valid_saved_token_no_browser(self):
        (self.root/'token.json').write_text('{}')
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=self.credentials) as load, \
             patch('googleapiclient.discovery.build', return_value='fake-api') as build, \
             patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow:
            self.assertEqual(connect_gmail(), 'fake-api')
        load.assert_called_once_with(str(self.root/'token.json'), SCOPES)
        flow.assert_not_called()
        self.assertFalse(build.call_args.kwargs['cache_discovery'])

    def test_expired_refresh_success(self):
        (self.root/'token.json').write_text('{}')
        self.credentials.expired = True
        self.credentials.refresh_token = 'FAKE'
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=self.credentials), \
             patch('google.auth.transport.requests.Request'), patch('googleapiclient.discovery.build'):
            connect_gmail()
        self.credentials.refresh.assert_called_once()

    def test_refresh_failure_does_not_replace_saved_token(self):
        token = self.root/'token.json'
        token.write_text('original')
        self.credentials.expired = True
        self.credentials.refresh.side_effect = OSError('offline')
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=self.credentials), \
             patch('google.auth.transport.requests.Request'), self.assertRaises(OSError):
            connect_gmail()
        self.assertEqual(token.read_text(), 'original')

    def test_missing_credentials_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, 'credentials.json'):
            connect_gmail()

    def test_first_login_writes_token_only_after_success(self):
        (self.root/'credentials.json').write_text('{}')
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow, \
             patch('googleapiclient.discovery.build'):
            flow.return_value.run_local_server.return_value = self.credentials
            connect_gmail()
        flow.return_value.run_local_server.assert_called_once_with(port=0)
        self.assertEqual((self.root/'token.json').read_text(), '{"fake":"test"}')

    def test_user_denies_login_no_token_or_api(self):
        (self.root/'credentials.json').write_text('{}')
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow, \
             patch('googleapiclient.discovery.build') as build:
            flow.return_value.run_local_server.side_effect = ValueError('denied')
            with self.assertRaises(ValueError):
                connect_gmail()
        build.assert_not_called()
        self.assertFalse((self.root/'token.json').exists())

    def test_revoked_refresh_token_starts_new_login(self):
        from google.auth.exceptions import RefreshError
        (self.root/'token.json').write_text('{}')
        (self.root/'credentials.json').write_text('{}')
        self.credentials.expired = True
        self.credentials.refresh.side_effect = RefreshError('invalid_grant: token revoked')
        fresh = Mock(valid=True)
        fresh.to_json.return_value = '{"fake":"new"}'
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=self.credentials), \
             patch('google.auth.transport.requests.Request'), patch('googleapiclient.discovery.build'), \
             patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow:
            flow.return_value.run_local_server.return_value = fresh
            connect_gmail()
        flow.return_value.run_local_server.assert_called_once()
        self.assertEqual((self.root/'token.json').read_text(), '{"fake":"new"}')
