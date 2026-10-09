import threading
import unittest
from unittest.mock import Mock, patch
from app import App, CATEGORIES, VERSION_LABEL
from mail_batch import collect_unprocessed


class BatchTests(unittest.TestCase):
    def test_pagination_and_deduplication(self):
        messages = Mock()
        messages.list.return_value.execute.side_effect = [
            {'messages': [{'id': 'a'}, {'id': 'b'}], 'nextPageToken': 'p2'},
            {'messages': [{'id': 'b'}, {'id': 'c'}]}]
        result = collect_unprocessed(messages, 5, threading.Event(), Mock())
        self.assertEqual([r['id'] for r in result], ['a', 'b', 'c'])
        self.assertEqual(messages.list.call_args.kwargs['pageToken'], 'p2')
        self.assertIn('-label:Agent/Обработано', messages.list.call_args.kwargs['q'])

    def test_repeated_page_token_fails_instead_of_infinite_loop(self):
        messages = Mock()
        messages.list.return_value.execute.return_value = {'nextPageToken': 'same'}
        with self.assertRaises(RuntimeError):
            collect_unprocessed(messages, 5, threading.Event(), Mock())
        self.assertEqual(messages.list.call_count, 2)

    def test_stop_during_collection(self):
        stop = threading.Event()
        messages = Mock()
        messages.list.return_value.execute.return_value = {'messages': [{'id': 'a'}], 'nextPageToken': 'p2'}
        result = collect_unprocessed(messages, 5, stop, lambda text: stop.set())
        self.assertEqual(len(result), 1)
        self.assertEqual(messages.list.call_count, 1)

    def make_app(self):
        app = App.__new__(App)
        app.gmail, app.log = Mock(), Mock()
        app.stop_sorting = threading.Event()
        labels = {'Agent/' + name: 'id-' + name for name in CATEGORIES}
        labels.update({'Agent/Обработано': 'processed', VERSION_LABEL: 'v2'})
        app.gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            'labels': [{'name': name, 'id': value} for name, value in labels.items()]}
        return app, app.gmail.users.return_value.messages.return_value

    def test_full_run_skips_processed_and_does_not_retry_invalid_in_loop(self):
        app, messages = self.make_app()
        messages.list.return_value.execute.side_effect = [
            {'messages': [{'id': 'old'}, {'id': 'invalid'}], 'nextPageToken': 'p2'},
            {'messages': [{'id': 'good'}]}]
        messages.get.return_value.execute.side_effect = [
            {'labelIds': ['processed'], 'payload': {}}, {'payload': {}}, {'payload': {}}]
        with patch('app.ask_model', side_effect=['wrong', 'Работа']) as model:
            app.sort_all({'limit': '2', 'endpoint': 'unused', 'model': 'unused', 'folder': 'unused'})
        self.assertEqual(model.call_count, 2)
        self.assertEqual(messages.modify.call_count, 1)
        self.assertEqual(messages.modify.call_args.kwargs['id'], 'good')
        self.assertIn('ошибок формата 1', app.log.call_args.args[0])
        self.assertIn('пропущено 1', app.log.call_args.args[0])

    def test_stop_finishes_current_and_leaves_rest_unmodified(self):
        app, messages = self.make_app()
        messages.list.return_value.execute.return_value = {'messages': [{'id': 'a'}, {'id': 'b'}]}
        messages.get.return_value.execute.return_value = {'payload': {}}
        def classify(*args):
            app.stop_sorting.set()
            return 'Работа'
        with patch('app.ask_model', side_effect=classify):
            app.sort_all({'limit': '2', 'endpoint': 'unused', 'model': 'unused', 'folder': 'unused'})
        self.assertEqual(messages.modify.call_count, 1)
        self.assertIn('Остановлено', app.log.call_args.args[0])
        self.assertIn('осталось из списка 1', app.log.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
