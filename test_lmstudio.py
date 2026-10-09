"""Opt-in integration checks: synthetic contacts, no Gmail access or sending."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from app import ask_model
from contacts import Contacts, DRAFT_SYSTEM, validate_draft
from attachment_selection import select_attachments
from catalog import Catalog


@unittest.skipUnless(os.environ.get('MAIL_AGENT_LIVE_TESTS') == '1', 'LM Studio tests are opt-in')
class LMStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.contacts = Contacts(Path(self.temp.name) / 'contacts.db')
        self.contacts.save('Иван Петров', 'ivan@example.com', ['начальник'])
        self.contacts.save('Анна Смирнова', 'anna@example.com', ['коллега'])

    def prepare(self, request, override='', examples=()):
        payload = json.dumps({'request': request, 'recipient_override': override,
                              'contacts': self.contacts.list(), 'provided_files': [],
                              'style_examples': list(examples)}, ensure_ascii=False)
        answer = ask_model(os.environ.get('MAIL_AGENT_API', 'http://127.0.0.1:22227/v1'),
                           os.environ.get('MAIL_AGENT_MODEL', 'qwen3.5-4b'), DRAFT_SYSTEM, payload)
        return validate_draft(answer, self.contacts, request, override)

    def test_alias_from_request(self):
        draft = self.prepare('Напиши начальнику, что отчёт готов. Без подписи.')
        self.assertEqual(draft['recipient'], 'ivan@example.com')
        self.assertTrue(draft['subject'] and draft['body'])

    def test_explicit_new_address(self):
        draft = self.prepare('Напиши на new.person@example.com: благодарю за встречу. Без подписи.')
        self.assertEqual(draft['recipient'], 'new.person@example.com')

    def test_recipient_field_has_priority(self):
        draft = self.prepare('Напиши начальнику, что встреча завершена.', override='коллега')
        self.assertEqual(draft['recipient'], 'anna@example.com')

    def test_request_selects_attachment_by_content(self):
        root = Path(self.temp.name).resolve() / 'attachments'
        root.mkdir()
        report = root / 'document.txt'
        report.write_text('Отчёт за сентябрь 7500', encoding='utf-8')
        catalog = Catalog(root)
        catalog.scan()
        draft = self.prepare('Напиши начальнику, что отчёт готов, и приложи отчёт за сентябрь.')
        self.assertTrue(draft['attachment_queries'])
        self.assertEqual(select_attachments(catalog, draft['attachment_queries']), [str(report)])

    def test_style_samples_do_not_supply_old_facts(self):
        draft = self.prepare('Напиши начальнику, что новый отчёт готов. Без подписи.', examples=[
            'Добрый день! Направляю счёт на 987654 рублей. Договор с компанией OldCompany согласован.'])
        self.assertEqual(draft['recipient'], 'ivan@example.com')
        self.assertNotIn('987654', draft['body'])
        self.assertNotIn('OldCompany', draft['body'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
