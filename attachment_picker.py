"""Choose saved attachments by human-readable source metadata, without OCR."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from attachment_selection import check_files


def source_info(path):
    try:
        sources=json.loads((path.parent/'.source.json').read_text(encoding='utf-8'))
        info=sources.get(path.name,{}) if isinstance(sources,dict) else {}
        return info if isinstance(info,dict) else {}
    except (OSError,ValueError):
        return {}


def attachment_name(root, value):
    path=Path(check_files(root,[value])[0])
    name=str(source_info(path).get('filename',path.name))
    return Path(name.replace('\\','/')).name or path.name


def available(root, query=''):
    root=Path(root).expanduser().resolve()
    words=query.casefold().replace('ё','е').split()
    rows=[]
    for path in root.rglob('*'):
        if not path.is_file() or any(p.startswith('.') for p in path.relative_to(root).parts):
            continue
        try:
            checked=check_files(root,[path])[0]
            info=source_info(path)
            row=dict(path=checked,name=attachment_name(root,path),sender=str(info.get('sender','')),
                     subject=str(info.get('subject','')),date=str(info.get('date','')),size=path.stat().st_size)
        except (ValueError,OSError):
            continue
        haystack=' '.join(row[k] for k in ('name','sender','subject','date')).casefold().replace('ё','е')
        if all(word in haystack for word in words):
            rows.append(row)
    return sorted(rows,key=lambda row:(row['date'],row['name']),reverse=True)


def choose_attachments(window, root, selected=()):
    popup=tk.Toplevel(window)
    from shortcuts import install
    install(popup)
    popup.title('Добавить почтовые вложения')
    scale=window.winfo_fpixels('1i')/96
    width=min(round(1000*scale),window.winfo_screenwidth()-80)
    height=min(round(560*scale),window.winfo_screenheight()-100)
    popup.geometry(f'{width}x{height}')
    frame=ttk.Frame(popup,padding=16)
    frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Выберите файлы из сохранённой почты. Для нескольких файлов удерживайте Ctrl.').pack(anchor='w')
    query=tk.StringVar()
    entry=ttk.Entry(frame,textvariable=query)
    entry.pack(fill='x',pady=10)
    tree=ttk.Treeview(frame,columns=('name','sender','subject','date','size'),show='headings',selectmode='extended')
    for key,title,width in [('name','Файл',230),('sender','Отправитель',170),('subject','Тема письма',230),('date','Дата',170),('size','Размер',80)]:
        tree.heading(key,text=title)
        tree.column(key,width=round(width*scale),minwidth=round(60*scale))
    scrollbar=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right',fill='y')
    tree.pack(fill='both',expand=True)
    count=ttk.Label(frame,text='')
    count.pack(anchor='w',pady=8)
    result=[]
    rows={}
    selected_set={str(Path(p).resolve()) for p in selected}
    def refresh(*args):
        tree.delete(*tree.get_children())
        rows.clear()
        for i,row in enumerate(available(root,query.get())):
            key=str(i)
            rows[key]=row
            size=f"{row['size']} Б" if row['size']<1024 else f"{row['size']/1024:.1f} КБ"
            tree.insert('', 'end', iid=key, values=(row['name'],row['sender'],row['subject'],row['date'],size))
            if row['path'] in selected_set:
                tree.selection_add(key)
        count.config(text=f'Найдено файлов: {len(rows)}. Поиск по имени, отправителю, теме и дате.')
    def accept():
        values=[rows[key]['path'] for key in tree.selection()]
        if not values:
            return
        try:
            result.extend(check_files(root,values))
        except ValueError as error:
            messagebox.showerror('Вложения',str(error),parent=popup)
            return
        popup.destroy()
    controls=ttk.Frame(frame)
    controls.pack(fill='x')
    ttk.Button(controls,text='Добавить выбранные',command=accept,style='Primary.TButton').pack(side='right')
    ttk.Button(controls,text='Отмена',command=popup.destroy).pack(side='right',padx=8)
    query.trace_add('write',refresh)
    tree.bind('<Double-1>',lambda event:accept())
    refresh()
    entry.focus_set()
    popup.transient(window)
    popup.grab_set()
    window.wait_window(popup)
    return result
