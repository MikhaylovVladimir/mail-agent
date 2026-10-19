import tempfile
import tkinter as tk
import unittest
import threading
from pathlib import Path
from unittest.mock import patch, Mock
from app import App
from contacts import Contacts


class InterfaceTests(unittest.TestCase):
    def widgets(self, root=None):
        root = root or self.window
        for child in root.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, title):
        return next(w for w in self.widgets() if w.winfo_class() == 'TButton' and w['text'] == title)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = tk.Tk()
        self.callback_errors = []
        self.window.report_callback_exception = lambda kind, value, trace: self.callback_errors.append(str(value))
        with patch('app.Contacts', return_value=Contacts(Path(self.temp.name) / 'contacts.sqlite3')):
            self.app = App(self.window)
        self.app.folder.set(self.temp.name)
        self.window.update()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()
        self.assertEqual(self.callback_errors, [], 'Tk callback failed')

    def test_navigation_keeps_draft_and_embeds_tools(self):
        self.app.prompt.insert('1.0', 'Запрос')
        self.app.body.insert('1.0', 'Черновик')
        for name in self.app.pages:
            self.app.show_page(name)
            self.window.update()
        self.assertEqual(self.app.prompt.get('1.0', 'end').strip(), 'Запрос')
        self.assertEqual(self.app.body.get('1.0', 'end').strip(), 'Черновик')
        self.assertFalse(any(isinstance(child, tk.Toplevel) for child in self.window.winfo_children()))
        self.app.show_page('Новое письмо')
        self.window.update()
        self.assertGreater(self.app.body.winfo_height(), 70)

    def test_new_letter_cancel_and_confirm(self):
        self.app.prompt.insert('1.0', 'Напиши отцу')
        self.app.recipient.set('father@example.com')
        with patch('app.messagebox.askyesno', return_value=False):
            self.app.new_letter()
        self.assertEqual(self.app.recipient.get(), 'father@example.com')
        with patch('app.messagebox.askyesno', return_value=True):
            self.app.new_letter()
        self.assertEqual(self.app.recipient.get(), '')
        self.assertEqual(self.app.prompt.get('1.0', 'end').strip(), '')

    def test_recipient_only_new_letter_requires_confirmation(self):
        self.app.recipient.set('a@example.com')
        with patch('app.messagebox.askyesno', return_value=False) as confirm:
            self.app.new_letter()
        confirm.assert_called_once()
        self.assertEqual(self.app.recipient.get(), 'a@example.com')

    def test_ui_updates_queued_by_worker_run_on_main_thread(self):
        seen = []
        main = threading.get_ident()
        worker = threading.Thread(target=lambda: self.app.post(lambda: seen.append(threading.get_ident())))
        worker.start()
        worker.join()
        self.assertEqual(seen, [])
        self.app.pump_ui()
        self.assertEqual(seen, [main])

    def test_worker_failure_restores_buttons(self):
        def fail(settings):
            raise ValueError('test failure')
        with patch('app.threading.Thread') as thread:
            self.app.run(fail)
            self.assertTrue(self.app.busy)
            thread.call_args.kwargs['target']()
            self.app.pump_ui()
        self.assertFalse(self.app.busy)
        self.assertEqual(str(self.app.voice_button['state']), 'normal')
        self.assertIn('test failure', self.app.journal.get('1.0', 'end'))

    def test_busy_does_not_start_second_task_or_clear_letter(self):
        self.app.prompt.insert('1.0', 'Сохранить запрос')
        self.app.busy = True
        action = unittest.mock.Mock()
        self.app.run(action)
        self.app.new_letter()
        action.assert_not_called()
        self.assertIn('Сохранить запрос', self.app.prompt.get('1.0','end'))

    def test_closed_window_ignores_worker_callbacks(self):
        self.app.closed = True
        callback = unittest.mock.Mock()
        self.app.post(callback)
        self.app.pump_ui()
        callback.assert_not_called()

    def test_catalog_folder_setting_refreshes_embedded_view(self):
        self.app.show_page('Вложения')
        previous = self.app.pages['Вложения'].winfo_children()[1]
        other = Path(self.temp.name) / 'other'
        self.app.folder.set(str(other))
        self.app.show_page('Вложения')
        self.assertFalse(previous.winfo_exists())
        self.assertTrue((other / '.catalog.sqlite3').exists())

    def test_contacts_crud_and_choose_recipient_through_ui(self):
        from tkinter import ttk
        self.app.show_page('Контакты')
        page = self.app.pages['Контакты']
        entries = [w for w in self.widgets(page) if w.winfo_class() == 'TEntry']
        for entry, value in zip(entries, ['Анна', 'anna@example.com', 'коллега']):
            entry.insert(0, value)
        self.button('Сохранить').invoke()
        self.app.pump_ui()
        self.assertEqual(self.app.contacts.resolve('коллега'), 'anna@example.com')
        tree = next(w for w in self.widgets(page) if isinstance(w, ttk.Treeview))
        tree.selection_set(tree.get_children()[0])
        tree.event_generate('<<TreeviewSelect>>')
        self.window.update()
        self.button('Выбрать получателем').invoke()
        self.assertEqual(self.app.recipient.get(), 'anna@example.com')
        self.app.show_page('Контакты')
        with patch('app.messagebox.askyesno', return_value=True):
            self.button('Удалить').invoke()
        self.assertFalse(self.app.contacts.list())

    def test_contacts_bad_address_ui_does_not_save(self):
        self.app.show_page('Контакты')
        entries = [w for w in self.widgets(self.app.pages['Контакты']) if w.winfo_class() == 'TEntry']
        entries[0].insert(0, 'Имя')
        entries[1].insert(0, 'not-email')
        with patch('app.messagebox.showerror') as error:
            self.button('Сохранить').invoke()
        error.assert_called_once()
        self.assertFalse(self.app.contacts.list())

    def test_optional_contact_salutation_is_saved(self):
        self.app.show_page('Контакты')
        entries = [w for w in self.widgets(self.app.pages['Контакты']) if w.winfo_class() == 'TEntry']
        for entry, value in zip(entries, ['Тестовый пользователь', 'test@example.com', 'тест', 'Иван Петрович']):
            entry.insert(0, value)
        self.button('Сохранить').invoke()
        self.assertEqual(self.app.contacts.list()[0]['salutation'], 'Иван Петрович')

    def test_catalog_scan_search_preview_buttons(self):
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        (Path(self.temp.name)/'report.txt').write_text('Отчёт 123456', encoding='utf-8')
        self.app.show_page('Вложения')
        page = self.app.pages['Вложения']
        checkbox = next(w for w in self.widgets(page) if w.winfo_class() == 'TCheckbutton')
        checkbox.invoke()  # Native text parsing only; no model calls.
        with patch('app.threading.Thread') as worker:
            self.button('Сканировать хранилище').invoke()
            worker.call_args.kwargs['target']()
            self.app.pump_ui()
        entry = next(w for w in self.widgets(page) if w.winfo_class() == 'TEntry')
        entry.insert(0,'123456')
        self.button('Найти').invoke()
        tree = next(w for w in self.widgets(page) if isinstance(w, ttk.Treeview))
        self.assertEqual(len(tree.get_children()), 1)
        tree.selection_set(tree.get_children()[0])
        tree.event_generate('<<TreeviewSelect>>')
        self.window.update()
        preview = next(w for w in self.widgets(page) if isinstance(w, ScrolledText))
        self.assertIn('Отчёт 123456', preview.get('1.0','end'))
        with patch('app.messagebox.showinfo') as info:
            self.button('Открыть исходное письмо').invoke()
        info.assert_called_once()

    def test_catalog_scan_failure_reenables_scan(self):
        self.app.show_page('Вложения')
        with patch('app.Catalog.scan', side_effect=OSError('disk error')), patch('app.threading.Thread') as worker:
            self.button('Сканировать хранилище').invoke()
            worker.call_args.kwargs['target']()
            self.app.pump_ui()
        self.assertEqual(str(self.button('Сканировать хранилище')['state']), 'normal')

    def test_attach_cancel_and_hidden_file_rejected(self):
        hidden = Path(self.temp.name)/'.secret'
        hidden.write_text('secret')
        with patch('app.filedialog.askopenfilenames', return_value=()):
            self.app.attach()
        self.assertFalse(self.app.files)
        with patch('app.filedialog.askopenfilenames', return_value=[str(hidden)]), patch('app.messagebox.showerror') as error:
            self.app.attach()
        error.assert_called_once()
        self.assertFalse(self.app.files)

    def test_attach_valid_file_and_clear(self):
        path = Path(self.temp.name)/'report.txt'
        path.write_text('report')
        with patch('app.filedialog.askopenfilenames', return_value=[str(path)]):
            self.app.attach()
        self.assertEqual(len(self.app.files), 1)
        self.app.clear_attachments()
        self.assertFalse(self.app.files)

    def test_voice_cancel_preserves_previous_draft(self):
        self.app.body.insert('1.0','Старое письмо')
        self.app.recorder = Mock()
        recorder = self.app.recorder
        self.app.cancel_voice()
        recorder.cancel.assert_called_once()
        self.assertIn('Старое письмо', self.app.body.get('1.0','end'))

    def test_voice_failed_transcription_preserves_recipient_and_recovers(self):
        self.app.recipient.set('father@example.com')
        self.app.recorder = Mock()
        with patch('app.transcribe', side_effect=ValueError('no speech')), patch('app.threading.Thread') as worker:
            self.app.dictate()
            worker.call_args.kwargs['target']()
            self.app.pump_ui()
        self.assertEqual(self.app.recipient.get(), 'father@example.com')
        self.assertFalse(self.app.busy)

    def test_voice_success_replaces_previous_recipient(self):
        self.app.recipient.set('father@example.com')
        self.app.recorder = Mock()
        with patch('app.transcribe', return_value='Напиши тестовому пользователю'), patch('app.threading.Thread') as worker:
            self.app.dictate()
            worker.call_args.kwargs['target']()
            self.app.pump_ui()
        self.assertEqual(self.app.recipient.get(), '')
        self.assertEqual(self.app.prompt.get('1.0','end').strip(), 'Напиши тестовому пользователю')

    def test_voice_missing_model_and_microphone_start_failure(self):
        for failpoint in ('app.validate_model', 'app.Recorder.start'):
            with self.subTest(failpoint=failpoint), patch(failpoint, side_effect=ValueError('failed')), patch('app.messagebox.showerror') as error:
                self.app.dictate()
                error.assert_called_once()
                self.assertIsNone(self.app.recorder)

    def test_connection_failure_does_not_enable_sending(self):
        with patch('app.connect_gmail', side_effect=OSError('offline')), self.assertRaises(OSError):
            self.app.connect({})
        self.assertIsNone(self.app.gmail)
        with patch('app.messagebox.showerror') as error:
            self.app.send()
        error.assert_called_once()
