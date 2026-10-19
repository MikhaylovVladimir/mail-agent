import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contacts import Contacts
from app import App, ask_model
from style_history import clean_example, sent_style_samples, MAX_SAMPLE_CHARS


def sent_mail(to='ivan@example.com', text='Добрый день!\nОтчёт готов.', labels=None):
    return {'labelIds': ['SENT'] if labels is None else labels,
            'payload': {'mimeType': 'text/plain', 'headers': [{'name': 'To', 'value': to}],
                        'body': {'data': base64.urlsafe_b64encode(text.encode()).decode()}}}


class StyleTests(unittest.TestCase):
    def test_quotes_signature_and_size_removed(self):
        self.assertEqual(clean_example('Добрый день!\n> чужая цитата\nСпасибо.\n--\nПодпись'), 'Добрый день!\nСпасибо.')
        self.assertEqual(clean_example('Готово\nOn Monday John wrote:\nЦитата'), 'Готово')
        self.assertEqual(len(clean_example('x' * 5000)), MAX_SAMPLE_CHARS)

    def test_only_sent_mail_to_exact_recipient(self):
        gmail = Mock()
        messages = gmail.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {'messages': [{'id': str(i)} for i in range(3)]}
        messages.get.return_value.execute.side_effect = [sent_mail(), sent_mail(to='other@example.com'), sent_mail(labels=['INBOX'])]
        self.assertEqual(sent_style_samples(gmail, 'ivan@example.com'), ['Добрый день!\nОтчёт готов.'])
        self.assertEqual(messages.list.call_args.kwargs['maxResults'], 5)
        self.assertIn('in:sent', messages.list.call_args.kwargs['q'])
        messages.attachments.assert_not_called()

    def test_no_gmail_or_invalid_email(self):
        self.assertEqual(sent_style_samples(None, 'ivan@example.com'), [])
        with self.assertRaises(ValueError):
            sent_style_samples(Mock(), 'ivan@example.com OR to:other@example.com')

    def test_model_refuses_external_address_before_network_request(self):
        with patch('app.urllib.request.build_opener') as network:
            with self.assertRaises(ValueError):
                ask_model('https://example.com/v1', 'model', 'system', 'private data')
            network.assert_not_called()

    def make_app(self, folder):
        app = App.__new__(App)
        app.contacts = Contacts(Path(folder) / 'contacts.db')
        app.contacts.save('Иван', 'ivan@example.com', ['начальник'])
        app.gmail = Mock()
        app.recipient, app.subject, app.body, app.log, app.attachments = (Mock() for _ in range(5))
        app.window = Mock()
        app.window.after.side_effect = lambda delay, callback: callback()
        return app

    def test_disabled_style_never_reads_mail(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder)
            answer = json.dumps({'recipient': 'начальник', 'subject': 'Отчёт', 'body': 'Готово'})
            with patch('app.ask_model', return_value=answer), patch('app.sent_style_samples') as history:
                app.draft({'prompt': 'Напиши начальнику', 'endpoint': 'unused', 'model': 'unused', 'files': [], 'use_style': False})
            history.assert_not_called()
            app.gmail.users.assert_not_called()

    def test_style_is_passed_only_after_resolving_recipient(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder)
            answer = json.dumps({'recipient': 'начальник', 'subject': 'Отчёт', 'body': 'Готово'})
            with patch('app.ask_model', return_value=answer) as model, patch('app.sent_style_samples', return_value=['Добрый день!']) as history:
                app.draft({'prompt': 'Напиши начальнику', 'endpoint': 'unused', 'model': 'unused', 'files': [], 'use_style': True})
            history.assert_called_once_with(app.gmail, 'ivan@example.com')
            self.assertEqual(model.call_count, 2)
            context = json.loads(model.call_args.args[3])
            self.assertEqual(context['style_examples'], [])  # Greeting-only samples carry no reusable text.
            self.assertEqual(context['recipient_override'], 'ivan@example.com')
            app.gmail.users.assert_not_called()

    def test_history_error_falls_back_to_official_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder)
            answer = json.dumps({'recipient': 'начальник', 'subject': 'Отчёт', 'body': 'Готово'})
            with patch('app.ask_model', return_value=answer) as model, patch('app.sent_style_samples', side_effect=TimeoutError):
                app.draft({'prompt': 'Напиши начальнику', 'endpoint': 'unused', 'model': 'unused', 'files': [], 'use_style': True})
            self.assertEqual(model.call_count, 1)
            app.body.insert.assert_called_once_with('1.0', 'Здравствуйте!\n\nГотово')
