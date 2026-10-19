import tempfile
import unittest
from pathlib import Path
from catalog import Catalog
from attachment_picker import available, attachment_name


class AttachmentPickerTests(unittest.TestCase):
    def test_original_names_metadata_and_hidden_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            sub=root/'opaque-id-123'
            sub.mkdir()
            path=sub/'0_document.txt'
            path.write_text('content')
            catalog=Catalog(root)
            catalog.record_source(path,dict(filename='Отчёт за сентябрь.txt',sender='Отправитель',subject='Проект',date='2026-10-19'))
            (root/'.secret').write_text('secret')
            rows=available(root,'отчет сентябрь')
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['name'],'Отчёт за сентябрь.txt')
            self.assertEqual(rows[0]['sender'],'Отправитель')
            self.assertEqual(len(available(root)),1)
            self.assertEqual(attachment_name(root,path),'Отчёт за сентябрь.txt')

    def test_unsafe_source_name_cannot_become_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'file.txt'
            path.write_text('x')
            Catalog(folder).record_source(path,dict(filename='../../outside.txt'))
            self.assertEqual(attachment_name(folder,path),'outside.txt')
            path.unlink()
            self.assertEqual(available(folder),[])

    def test_picker_accept_and_cancel_in_real_tk(self):
        import tkinter as tk
        from tkinter import ttk
        from attachment_picker import choose_attachments
        root=tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'report.txt'
                path.write_text('report')
                def find(widget,kind):
                    for child in widget.winfo_children():
                        if isinstance(child,kind):
                            yield child
                        yield from find(child,kind)
                def select():
                    popup=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                    tree=next(find(popup,ttk.Treeview))
                    tree.selection_set(tree.get_children()[0])
                    button=next(w for w in find(popup,ttk.Button) if w['text']=='Добавить выбранные')
                    button.invoke()
                root.after(100,select)
                self.assertEqual(choose_attachments(root,folder),[str(path.resolve())])
                root.after(100,lambda:next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel)).destroy())
                self.assertEqual(choose_attachments(root,folder),[])
        finally:
            root.destroy()
