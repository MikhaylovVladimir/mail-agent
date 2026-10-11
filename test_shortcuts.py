import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from shortcuts import handle, install


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.window = tk.Tk()
        install(self.window)
        self.text = tk.Text(self.window, undo=True)
        self.text.pack()
        self.entry = ttk.Entry(self.window)
        self.entry.pack()
        self.window.update()

    def tearDown(self):
        self.window.destroy()

    def key(self, widget, code, shift=False):
        with patch('shortcuts.sys.platform', 'win32'):
            return handle(SimpleNamespace(widget=widget, keycode=code, keysym='Cyrillic_es', state=4 | int(shift)))

    def test_copy_paste_cut_select_on_russian_layout(self):
        self.text.insert('1.0', 'Русский текст')
        self.key(self.text, 65)
        self.key(self.text, 67)
        self.assertEqual(self.window.clipboard_get(), 'Русский текст')
        self.key(self.entry, 86)
        self.assertEqual(self.entry.get(), 'Русский текст')
        self.key(self.entry, 65)
        self.key(self.entry, 88)
        self.assertEqual(self.entry.get(), '')

    def test_undo_redo_and_focus_binding(self):
        self.text.focus_force()
        self.window.update()
        self.assertTrue(any(tag.startswith('MailEditing') for tag in self.text.bindtags()))
        self.text.insert('1.0', 'Отчёт')
        self.text.edit_separator()
        self.key(self.text, 90)
        self.assertEqual(self.text.get('1.0', 'end').strip(), '')
        self.key(self.text, 90, shift=True)
        self.assertEqual(self.text.get('1.0', 'end').strip(), 'Отчёт')
