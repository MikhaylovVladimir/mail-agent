"""Read bounded style examples from sent mail to a confirmed recipient."""
import base64
import re
from email.utils import getaddresses
from contacts import valid_email

MAX_SAMPLES = 5
MAX_SAMPLE_CHARS = 1200


def walk_parts(payload):
    yield payload
    for part in payload.get('parts', []):
        yield from walk_parts(part)


def clean_example(text):
    lines = []
    for line in text.splitlines():
        if (line.strip() in {'--', '-- ', '-----Original Message-----', '---------- Forwarded message ---------'}
                or re.match(r'^On .+wrote:\s*$', line, re.I)
                or re.match(r'^.+(?:писал|писала|пишет)\s*:\s*$', line, re.I)):
            break
        if not line.lstrip().startswith('>'):
            lines.append(line)
    return '\n'.join(lines).strip()[:MAX_SAMPLE_CHARS]


def sent_style_samples(gmail, recipient):
    if not valid_email(recipient):
        raise ValueError('Для истории нужен один подтверждённый email.')
    if gmail is None:
        return []
    api = gmail.users().messages()
    response = api.list(userId='me', q=f'in:sent to:{recipient} -in:trash', maxResults=MAX_SAMPLES).execute()
    samples = []
    for item in response.get('messages', [])[:MAX_SAMPLES]:
        message = api.get(userId='me', id=item['id'], format='full').execute()
        # Independently verify labels and headers instead of trusting search results alone.
        if 'SENT' not in message.get('labelIds', []):
            continue
        payload = message.get('payload', {})
        headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
        addresses = {address.casefold() for _, address in getaddresses([headers.get('to', '')])}
        if recipient.casefold() not in addresses:
            continue
        texts = []
        for part in walk_parts(payload):
            if part.get('filename') or part.get('mimeType') != 'text/plain':
                continue
            data = part.get('body', {}).get('data')
            if not data:
                continue
            raw = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
            content_type = next((h['value'] for h in part.get('headers', [])
                                 if h['name'].lower() == 'content-type'), '')
            charset = re.search(r'charset=["\']?([^;"\'\s]+)', content_type, re.I)
            try:
                text = raw.decode(charset.group(1) if charset else 'utf-8', errors='replace')
            except LookupError:
                text = raw.decode('utf-8', errors='replace')
            texts.append(text)
        example = clean_example('\n'.join(texts))
        if example:
            samples.append(example)
    return samples
