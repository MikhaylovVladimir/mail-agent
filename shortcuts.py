"""Windows physical editing shortcuts, independent of keyboard layout."""
import sys
import tkinter as tk

KEYS = {65: 'a', 67: 'c', 86: 'v', 88: 'x', 89: 'y', 90: 'z'}


def handle(event):
    widget = event.widget
    if not isinstance(widget, (tk.Text, tk.Entry)) and widget.winfo_class() != 'TEntry':
        return None
    if not event.state & 4 or event.state & (8 | 0x20000):
        return None
    key = KEYS.get(event.keycode) if sys.platform == 'win32' else event.keysym.lower()
    actions = {'c': '<<Copy>>', 'v': '<<Paste>>', 'x': '<<Cut>>',
               'z': '<<Redo>>' if event.state & 1 else '<<Undo>>', 'y': '<<Redo>>'}
    if key == 'a':
        if isinstance(widget, tk.Text):
            widget.tag_add('sel', '1.0', 'end-1c')
        else:
            widget.selection_range(0, 'end')
        return 'break'
    if key in actions:
        try:
            widget.event_generate(actions[key])
        except tk.TclError:
            pass
        return 'break'
    return None


def install(window):
    tag = 'MailEditing' + str(id(window))
    window.bind_class(tag, '<KeyPress>', handle)
    def focus(event):
        widget = event.widget
        if widget.winfo_class() in ('Text', 'Entry', 'TEntry'):
            tags = widget.bindtags()
            if tag not in tags:
                widget.bindtags((tags[0], tag, *tags[1:]))
    window.bind('<FocusIn>', focus, add='+')
