"""Resolve attachment requests against the local catalog only."""
from pathlib import Path
import re


def attachment_requested(request):
    return re.search(r'\b(?:приложи(?:ть|те)?|прикрепи(?:ть|те)?|вложи(?:ть|те)?)\b', request.casefold()) is not None


def check_files(root, paths):
    root = Path(root).expanduser().resolve()
    checked = []
    for value in paths:
        path = Path(value).resolve()
        if not path.is_relative_to(root) or not path.is_file() or any(
                part.startswith('.') for part in path.relative_to(root).parts):
            raise ValueError('Вложение отсутствует или не является файлом почтового хранилища: ' + path.name)
        if str(path) not in checked:
            checked.append(str(path))
    return checked


def select_attachments(catalog, queries, manual=()):
    if manual:
        return check_files(catalog.root, manual)
    chosen = []
    for query in queries:
        matches = catalog.search(query)
        if not matches:
            raise ValueError(f'Не найден файл по запросу «{query}». Просканируйте каталог или выберите вложение вручную.')
        if len(matches) > 1:
            names = '; '.join(row['name'] for row in matches[:5])
            raise ValueError(f'Для «{query}» найдено {len(matches)} файлов: {names}. '
                             'Уточните запрос или прикрепите нужный файл вручную и повторите подготовку.')
        chosen.append(str(catalog.file_path(matches[0]['path'])))
    return check_files(catalog.root, chosen)
