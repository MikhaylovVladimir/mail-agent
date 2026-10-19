import base64
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch
from gmail_autotest import make_message, run
from mail_fixtures import CASES


class GmailAutotestTests(unittest.TestCase):
    def test_fixtures_cover_all_categories_without_real_addresses(self):
        from app import CATEGORIES
        self.assertEqual({case[1] for case in CASES},set(CATEGORIES))
        self.assertEqual(len({case[0] for case in CASES}),18)
        for case in CASES:
            with self.subTest(case=case[0]):
                message=make_message(case,'owner@example.com','test-run')
                self.assertIn('@autotest.invalid',message['From'])
                self.assertEqual(message['X-Mail-Agent-Test'],'test-run')
                self.assertNotIn(case[0],message['Subject'])

    def test_import_only_own_batch_and_report_no_send(self):
        gmail=Mock()
        api=gmail.users.return_value
        api.getProfile.return_value.execute.return_value={'emailAddress':'owner@example.com'}
        api.labels.return_value.create.return_value.execute.return_value={'id':'test-label'}
        api.labels.return_value.list.return_value.execute.return_value={'labels':[{'id':'cat','name':'Agent/Работа'}]}
        api.messages.return_value.import_.return_value.execute.return_value={'id':'synthetic-id'}
        api.messages.return_value.get.return_value.execute.return_value={'labelIds':['cat']}
        with tempfile.TemporaryDirectory() as folder, patch('gmail_autotest.CASES',[CASES[6]]), patch('gmail_autotest.App.sort') as sort:
            result=run(gmail,'unused','unused',folder,log=Mock())
            self.assertEqual(result['passed'],1)
            self.assertEqual(sort.call_args.args[0]['message_ids'],['synthetic-id'])
            self.assertTrue((Path(folder)/'results.json').is_file())
            api.messages.return_value.send.assert_not_called()
            request=api.messages.return_value.import_.call_args.kwargs
            self.assertTrue(request['neverMarkSpam'])
            parsed=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(request['body']['raw']))
            self.assertEqual(parsed['To'],'owner@example.com')

    def test_foreign_account_manifest_rejected_before_import(self):
        import json
        gmail=Mock()
        api=gmail.users.return_value
        api.getProfile.return_value.execute.return_value={'emailAddress':'owner@example.com'}
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'manifest.json').write_text(json.dumps({'account':'another-account','run_id':'x','cases':[]}))
            with self.assertRaises(ValueError):
                run(gmail,'unused','unused',folder,log=Mock())
        api.messages.return_value.import_.assert_not_called()
