"""Local attachment index. No network requests or file execution."""
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from contextlib import contextmanager

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 200000


def extract_text(path, ocr=None):
    if path.stat().st_size > MAX_BYTES:
        return '', 'Слишком большой файл (больше 20 МБ)'
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        from document_reader import read_pdf
        return read_pdf(path, ocr)
    if suffix in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}:
        from document_reader import read_image
        return read_image(path, ocr)
    if suffix in {'.txt', '.csv', '.md', '.log'}:
        data = path.read_bytes()
        for encoding in ('utf-8-sig', 'utf-16', 'cp1251'):
            try:
                return data.decode(encoding)[:MAX_TEXT], 'Текст извлечён'
            except UnicodeError:
                pass
        return '', 'Неизвестная кодировка'
    if suffix == '.docx':
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > MAX_BYTES:
                return '', 'Слишком большой документ'
            tree = ElementTree.fromstring(archive.read(info))
            text = '\n'.join(''.join(p.itertext()) for p in tree.iter()
                             if p.tag.endswith('}p'))
            return text[:MAX_TEXT], 'Текст извлечён'
    return '', 'Формат пока не поддерживается'


def genre(text):
    # Explicit heuristic: these are suggestions, not model-certified categories.
    value = text.casefold()
    for name, words in [('Резюме', ('резюме', 'curriculum vitae')),
                        ('Договор', ('договор', 'contract')),
                        ('Счёт', ('счет на оплату', 'счёт на оплату', 'invoice')),
                        ('Отчёт', ('отчёт', 'отчет', 'report'))]:
        if any(word in value for word in words):
            return name
    return 'Не определён'


class Catalog:
    def __init__(self, root, ocr=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / '.catalog.sqlite3'
        self.ocr = ocr
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, name TEXT, digest TEXT, text TEXT, status TEXT,
                genre TEXT, sender TEXT, date TEXT, subject TEXT, message_id TEXT,
                active INTEGER DEFAULT 1)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record_source(self, path, source):
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError('Файл вне хранилища')
        sidecar = resolved.parent / '.source.json'
        if sidecar.exists():
            sources = json.loads(sidecar.read_text(encoding='utf-8'))
        else:
            sources = {}
        sources[resolved.name] = source
        temporary = sidecar.with_suffix('.tmp')
        temporary.write_text(json.dumps(sources, ensure_ascii=False), encoding='utf-8')
        temporary.replace(sidecar)

    def scan(self):
        count = 0
        with self.connect() as db:
            db.execute('UPDATE files SET active=0')
            for path in self.root.rglob('*'):
                if not path.is_file() or path.name.startswith('.'):
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(self.root):
                    continue
                relative = str(path.relative_to(self.root))
                source = {}
                sidecar = path.parent / '.source.json'
                if sidecar.exists():
                    try:
                        source = json.loads(sidecar.read_text(encoding='utf-8')).get(path.name, {})
                    except (ValueError, OSError):
                        pass
                try:
                    if path.stat().st_size > MAX_BYTES:
                        digest = f'large:{path.stat().st_size}:{path.stat().st_mtime_ns}'
                    else:
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    digest = 'reader-v2:' + getattr(self.ocr, 'cache_key', 'no-ocr') + ':' + digest
                    old = db.execute('SELECT digest,text,status,genre FROM files WHERE path=?', (relative,)).fetchone()
                    if old and old[0] == digest and not any(marker in old[2] for marker in
                                                          ('Ошибка', 'Частично', 'недоступно')):
                        text, status, kind = old[1:]
                    else:
                        text, status = extract_text(path, self.ocr)
                        kind = genre(text)
                except Exception as error:
                    digest, text, status, kind = '', '', 'Ошибка чтения: ' + type(error).__name__, 'Не определён'
                db.execute('''INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,1)''',
                           (relative, source.get('filename', path.name), digest, text, status, kind,
                            source.get('sender', ''), source.get('date', ''), source.get('subject', ''),
                            source.get('message_id', '')))
                count += 1
        return count

    def search(self, query=''):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute('SELECT * FROM files WHERE active=1 ORDER BY date DESC,path')]
        words = query.casefold().split()
        return [row for row in rows if all(word in ' '.join(str(row[k]) for k in
                ('name', 'text', 'sender', 'subject', 'genre')).casefold() for word in words)]

    def file_path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError('Файл отсутствует или находится вне хранилища')
        return path
