"""Collect message IDs before changing labels, so pagination cannot skip mail."""
UNPROCESSED_QUERY = '-label:Agent/Обработано -in:trash -in:spam -in:sent -in:drafts'


def collect_unprocessed(messages, page_size, stop, progress):
    items, ids, tokens = [], set(), set()
    token = None
    while not stop.is_set():
        params = {'userId': 'me', 'q': UNPROCESSED_QUERY, 'maxResults': page_size}
        if token:
            params['pageToken'] = token
        page = messages.list(**params).execute()
        for item in page.get('messages', []):
            if item['id'] not in ids:
                ids.add(item['id'])
                items.append({'id': item['id']})
        progress(f'Собирается список необработанных писем: {len(items)}')
        token = page.get('nextPageToken')
        if not token:
            break
        if token in tokens:
            raise RuntimeError('Gmail повторил токен страницы; сбор остановлен без изменения писем.')
        tokens.add(token)
    return items
