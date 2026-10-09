import unittest
import tempfile
from pathlib import Path
import base64
from unittest.mock import Mock, patch
from app import App, CATEGORIES, VERSION_LABEL, category_changes
from catalog import Catalog


class SortingTests(unittest.TestCase):
    def setUp(self):
        self.labels = {'Agent/' + name: 'id-' + name for name in CATEGORIES}
        self.labels.update({'Agent/Обработано': 'processed', VERSION_LABEL: 'v2'})

    def test_replaces_categories_preserves_user_labels(self):
        change = category_changes('Безопасность', self.labels,
                                  ['id-Личное', 'id-Прочее', 'INBOX', 'STARRED', 'custom'])
        self.assertEqual(set(change['removeLabelIds']), {'id-Личное', 'id-Прочее'})
        self.assertEqual(set(change['addLabelIds']), {'id-Безопасность', 'processed', 'v2'})

    def test_quarantine_and_archived_mail(self):
        change = category_changes('Карантин', self.labels, ['INBOX'])
        self.assertIn('INBOX', change['removeLabelIds'])
        change = category_changes('Рассылки', self.labels, ['id-Карантин'])
        self.assertNotIn('INBOX', change['addLabelIds'])
        self.assertEqual(change['removeLabelIds'], ['id-Карантин'])

    def test_invalid_model_answer_does_not_mark_processed(self):
        app = App.__new__(App)
        app.gmail = Mock()
        app.log = Mock()
        api = app.gmail.users.return_value
        api.labels.return_value.list.return_value.execute.return_value = {
            'labels': [{'name': n, 'id': v} for n, v in self.labels.items()]}
        messages = api.messages.return_value
        messages.list.return_value.execute.return_value = {'messages': [{'id': 'mail-1'}]}
        messages.get.return_value.execute.return_value = {'payload': {}, 'labelIds': ['id-Вакансии']}
        with patch('app.ask_model', return_value='Неверный ответ'):
            app.sort({'limit': '5', 'endpoint': 'unused', 'model': 'unused', 'folder': 'unused'}, reprocess=True)
        self.assertIn('label:Agent/Обработано -label:Agent/Правила-v2', messages.list.call_args.kwargs['q'])
        messages.modify.assert_not_called()
        self.assertIn('обработано 0 писем', app.log.call_args.args[0])

    def test_attachment_saved_with_source_and_quarantine_not_downloaded(self):
        for category in ('Работа', 'Карантин'):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as folder:
                app = App.__new__(App)
                app.gmail, app.log = Mock(), Mock()
                api = app.gmail.users.return_value
                api.labels.return_value.list.return_value.execute.return_value = {
                    'labels': [{'name': n, 'id': v} for n, v in self.labels.items()]}
                messages = api.messages.return_value
                messages.list.return_value.execute.return_value = {'messages': [{'id': 'abc123'}]}
                messages.get.return_value.execute.return_value = {'labelIds': ['INBOX'], 'payload': {
                    'headers': [{'name': 'From', 'value': 'sender@example.com'},
                                {'name': 'Subject', 'value': 'Отчёт'}],
                    'parts': [{'filename': 'report.txt', 'body': {'attachmentId': 'attach1'}}]}}
                messages.attachments.return_value.get.return_value.execute.return_value = {
                    'data': base64.urlsafe_b64encode('Отчёт за сентябрь'.encode()).decode()}
                with patch('app.ask_model', return_value=category):
                    app.sort({'limit': '5', 'endpoint': 'unused', 'model': 'unused', 'folder': folder})
                if category == 'Карантин':
                    messages.attachments.assert_not_called()
                    self.assertEqual(list(Path(folder).iterdir()), [])
                else:
                    catalog = Catalog(folder)
                    catalog.scan()
                    row = catalog.search('сентябрь')[0]
                    self.assertEqual(row['message_id'], 'abc123')
                    self.assertEqual(row['sender'], 'sender@example.com')
                    self.assertEqual(row['name'], 'report.txt')


if __name__ == '__main__':
    unittest.main()
