import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contacts import Contacts, validate_draft
from app import App


class ContactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Contacts(Path(self.temp.name) / 'contacts.sqlite3')
        self.key = self.store.save('Иван Петров', 'ivan@example.com', ['начальник', 'руководитель'])

    def answer(self, recipient='начальник', **kwargs):
        return json.dumps(dict(recipient=recipient, subject='Отчёт готов', body='Добрый день! Отчёт готов.', **kwargs))

    def test_persistence_case_alias_and_update(self):
        self.assertEqual(Contacts(self.store.path).resolve('  НАЧАЛЬНИК '), 'ivan@example.com')
        self.store.save('Иван Петров', 'new@example.com', ['директор'], self.key)
        self.assertEqual(self.store.resolve('директор'), 'new@example.com')
        with self.assertRaises(ValueError):
            self.store.resolve('начальник')
        self.store.delete(self.key)
        self.assertEqual(self.store.list(), [])

    def test_unknown_and_ambiguous_contacts(self):
        with self.assertRaises(ValueError):
            self.store.resolve('Пётр')
        self.store.save('Другой Иван', 'other@example.com', ['начальник'])
        with self.assertRaisesRegex(ValueError, 'неоднозначен'):
            self.store.resolve('начальник')

    def test_no_header_injection_or_multiple_addresses(self):
        for address in ('a@example.com\nBcc: evil@example.com', 'a@example.com,b@example.com', 'bad'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.store.save('Контакт', address)

    def test_draft_alias_explicit_address_and_override(self):
        self.assertEqual(validate_draft(self.answer(), self.store, 'Напиши начальнику')['recipient'], 'ivan@example.com')
        self.assertEqual(validate_draft(self.answer('new@example.com'), self.store,
                                       'Напиши на new@example.com')['recipient'], 'new@example.com')
        self.assertEqual(validate_draft(self.answer('fake@example.com'), self.store,
                                       'Отчёт готов', 'руководитель')['recipient'], 'ivan@example.com')

    def test_bad_json_unknown_address_and_missing_fields_rejected(self):
        for answer in ('not json', '{}', self.answer('fake@example.com'), self.answer('неизвестный')):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                validate_draft(answer, self.store, 'Напиши начальнику')

    def test_draft_prepares_fields_without_sending(self):
        app = App.__new__(App)
        app.contacts = self.store
        app.gmail = Mock()
        app.recipient, app.subject, app.body, app.log = Mock(), Mock(), Mock(), Mock()
        app.window = Mock()
        app.window.after.side_effect = lambda delay, callback: callback()
        with patch('app.ask_model', return_value=self.answer()):
            app.draft({'prompt': 'Напиши начальнику: отчёт готов', 'recipient': '',
                       'endpoint': 'unused', 'model': 'unused', 'files': []})
        app.recipient.set.assert_called_once_with('ivan@example.com')
        app.subject.set.assert_called_once_with('Отчёт готов')
        app.gmail.users.assert_not_called()

    def test_cancel_send_makes_no_gmail_request(self):
        app = App.__new__(App)
        app.contacts = self.store
        app.gmail = Mock()
        app.recipient, app.subject, app.body = Mock(), Mock(), Mock()
        app.recipient.get.return_value = 'начальник'
        app.subject.get.return_value = 'Отчёт'
        app.body.get.return_value = 'Готово'
        app.files = []
        with patch('app.messagebox.askyesno', return_value=False):
            app.send()
        app.gmail.users.assert_not_called()


if __name__ == '__main__':
    unittest.main()
