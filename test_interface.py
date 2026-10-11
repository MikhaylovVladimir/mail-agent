import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from app import App
from contacts import Contacts


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = tk.Tk()
        with patch('app.Contacts', return_value=Contacts(Path(self.temp.name) / 'contacts.sqlite3')):
            self.app = App(self.window)
        self.app.folder.set(self.temp.name)
        self.window.update()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

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
