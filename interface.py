"""Desktop layout, independent of Gmail and model processing."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageDraw, ImageTk


def enable_dpi_awareness():
    """Call before Tk so Windows never stretches the rendered window bitmap."""
    import sys
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def rounded_buttons(window, style, scale):
    # Draw at the display's actual pixel density; keep references for Tk.
    window.button_images = []
    size = max(24, round(32 * scale))
    border = round(8 * scale)
    for name, colors in [('Soft', ('#e8edf5', '#dce5f1', '#eef1f6')),
                         ('Accent', ('#365fdf', '#2b50c8', '#c5cede'))]:
        images = []
        for color in colors:
            image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(image).rounded_rectangle((0, 0, size-1, size-1), radius=border, fill=color)
            photo = ImageTk.PhotoImage(image, master=window)
            window.button_images.append(photo)
            images.append(photo)
        element = name + '.rounded'
        style.element_create(element, 'image', images[0], ('disabled', images[2]),
                             ('active', images[1]), border=border, sticky='nsew')
        target = 'TButton' if name == 'Soft' else 'Primary.TButton'
        style.layout(target, [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [
                ('Button.focus', {'sticky': 'nsew', 'children': [
                    ('Button.label', {'sticky': 'nsew'})]})]})]})])
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((0, 0, size-1, size-1), radius=border,
                                            fill='white', outline='#d5ddea', width=max(1, round(scale)))
    photo = ImageTk.PhotoImage(image, master=window)
    window.button_images.append(photo)
    style.element_create('Rounded.field', 'image', photo, border=border, sticky='nsew')
    style.layout('TEntry', [('Rounded.field', {'sticky': 'nsew', 'children': [
        ('Entry.padding', {'sticky': 'nsew', 'children': [('Entry.textarea', {'sticky': 'nsew'})]})]})])


def build(app):
    window = app.window
    from shortcuts import install
    install(window)
    scale = window.winfo_fpixels('1i') / 96
    window.geometry(f'{round(1100 * scale)}x{round(780 * scale)}')
    window.minsize(round(1020 * scale), round(720 * scale))
    window.configure(bg='#f3f5fa')
    style = ttk.Style(window)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 10), background='#f3f5fa', foreground='#25324a')
    style.configure('TButton', padding=(round(12*scale), round(7*scale)), background='#e7ecf5', borderwidth=0)
    style.map('TButton', background=[('active', '#d9e3f4')])
    style.configure('Primary.TButton', background='#365fdf', foreground='white')
    style.map('Primary.TButton', background=[('active', '#284ec7'), ('disabled', '#c4cede')])
    rounded_buttons(window, style, scale)
    for target in ('TButton', 'Primary.TButton'):
        style.configure(target, background='#f3f5fa')
        style.map(target, background=[])
    style.configure('Title.TLabel', font=('Segoe UI', 21, 'bold'))
    style.configure('Muted.TLabel', foreground='#6a7890')
    style.configure('TEntry', padding=8, fieldbackground='white')
    style.configure('Treeview', rowheight=32, fieldbackground='white', background='white')
    style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), padding=8)
    header = ttk.Frame(window, padding=(24, 16))
    header.pack(fill='x')
    ttk.Label(header, text='Почтовый агент', font=('Segoe UI', 16, 'bold')).pack(side='left')
    ttk.Label(header, text='Локальная обработка · Gmail', style='Muted.TLabel').pack(side='right')
    shell = ttk.Frame(window)
    shell.pack(fill='both', expand=True)
    sidebar = ttk.Frame(shell, padding=(16, 18), width=190)
    sidebar.pack(side='left', fill='y')
    content = ttk.Frame(shell, padding=(22, 12, 24, 12))
    content.pack(side='left', fill='both', expand=True)
    content.rowconfigure(0, weight=1)
    content.columnconfigure(0, weight=1)
    app.pages = {}
    app.nav_buttons = {}
    for name in ('Почта', 'Новое письмо', 'Вложения', 'Контакты', 'Настройки'):
        page = ttk.Frame(content)
        page.grid(row=0, column=0, sticky='nsew')
        app.pages[name] = page
        button = ttk.Button(sidebar, text=name, command=lambda n=name: app.show_page(n))
        button.pack(fill='x', pady=5)
        app.nav_buttons[name] = button
        ttk.Label(page, text=name, style='Title.TLabel').pack(anchor='w', pady=(0, 16))
    app.buttons = []

    def button(parent, title, command, primary=False):
        widget = ttk.Button(parent, text=title, command=command,
                            style='Primary.TButton' if primary else 'TButton')
        widget.pack(side='left', padx=(0, 8), pady=6)
        app.buttons.append(widget)
        return widget

    def field(parent, title, variable):
        ttk.Label(parent, text=title).pack(anchor='w', pady=(10, 4))
        ttk.Entry(parent, textvariable=variable).pack(fill='x')

    def text(parent, height):
        widget = ScrolledText(parent, height=height, font=('Segoe UI', 11), wrap='word',
                              undo=True, autoseparators=True, maxundo=100,
                              relief='flat', bd=0, padx=14, pady=12, background='white',
                              foreground='#25324a', insertbackground='#365fdf')
        return widget

    mail = app.pages['Почта']
    ttk.Label(mail, text='Порядок во входящих', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
    ttk.Label(mail, text='Разберите новую и старую почту. Уже обработанные письма будут пропущены.',
              style='Muted.TLabel').pack(anchor='w', pady=10)
    row = ttk.Frame(mail)
    row.pack(fill='x')
    button(row, 'Подключить Gmail', lambda: app.run(app.connect))
    button(row, 'Разобрать партию', lambda: app.run(app.sort))
    row = ttk.Frame(mail)
    row.pack(fill='x', pady=12)
    button(row, 'Разобрать всю почту', lambda: app.run(app.sort_all), True)
    app.stop_button = ttk.Button(row, text='Остановить', state='disabled', command=app.request_stop)
    app.stop_button.pack(side='left')
    app.sort_progress = ttk.Progressbar(mail, mode='determinate')
    app.sort_progress.pack(fill='x', pady=12)
    ttk.Label(mail, text='Результаты обработки', font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=8)
    app.journal = text(mail, 12)
    app.journal.config(state='disabled')
    app.journal.pack(fill='both', expand=True)
    row = ttk.Frame(mail)
    row.pack(fill='x', pady=8)
    button(row, 'Пересортировать по новым правилам', lambda: app.run(app.resort))

    letter = app.pages['Новое письмо']
    ttk.Label(letter, text='Что нужно написать?', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    app.prompt = text(letter, 3)
    app.prompt.pack(fill='x', pady=8)
    row = ttk.Frame(letter)
    row.pack(fill='x')
    app.voice_button = ttk.Button(row, text='Диктовать запрос', command=app.dictate)
    app.voice_button.pack(side='left', padx=(0, 8))
    app.voice_cancel = ttk.Button(row, text='Отменить запись', state='disabled', command=app.cancel_voice)
    app.voice_cancel.pack(side='left')
    button(row, 'Подготовить черновик', lambda: app.run(app.draft), True)
    app.draft_alert = ttk.Label(letter, text='', foreground='#b42318', wraplength=850)
    app.draft_alert.pack(fill='x', pady=(3,0))
    app.use_style = tk.BooleanVar(value=True)
    ttk.Checkbutton(letter, text='Учитывать мой стиль переписки · официальный тон', variable=app.use_style).pack(anchor='w', pady=6)
    field(letter, 'Кому · email, имя или псевдоним; можно указать в запросе', app.recipient)
    app.recipient_hint = ttk.Label(letter, text='Если поле пустое, получатель определяется из запроса.', style='Muted.TLabel')
    app.recipient_hint.pack(anchor='w', pady=(3,0))
    field(letter, 'Тема', app.subject)
    app.body = text(letter, 6)
    app.body.pack(fill='both', expand=True, pady=12)
    app.attachments = ttk.Label(letter, text='Вложений нет', wraplength=850)
    app.attachments.pack(anchor='w')
    row = ttk.Frame(letter)
    row.pack(fill='x')
    button(row, 'Добавить файлы', app.attach)
    button(row, 'Убрать вложения', app.clear_attachments)
    button(row, 'Новое письмо', app.new_letter)
    button(row, 'Проверить и отправить', app.send, True)

    settings = app.pages['Настройки']
    for title, variable in [('Адрес LM Studio API', app.endpoint), ('Модель для писем и OCR', app.model),
                            ('Писем в одной партии', app.limit), ('Хранилище почтовых вложений', app.folder)]:
        field(settings, title, variable)
    ttk.Label(settings, text='Распознавание речи работает отдельной локальной моделью.', style='Muted.TLabel').pack(anchor='w', pady=20)
    app.voice_settings = ttk.Button(settings, text='Выбрать модель речи…', command=app.choose_voice_model)
    app.voice_settings.pack(anchor='w')
    ttk.Label(settings, text='Для подготовки писем запустите локальный сервер LM Studio.\nОтправка выполняется после вашего подтверждения.',
              style='Muted.TLabel').pack(anchor='w', pady=20)
    footer = ttk.Frame(window, padding=(24, 10))
    footer.pack(side='bottom', fill='x', before=shell)
    app.status = ttk.Label(footer, text='Готово. Подключите Gmail в разделе «Почта».', wraplength=900)
    app.status.pack(side='left')
    ttk.Button(footer, text='Открыть журнал', command=lambda: app.show_page('Почта')).pack(side='right')
    app.show_page('Новое письмо')
