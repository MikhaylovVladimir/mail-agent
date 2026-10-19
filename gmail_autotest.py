"""Import and classify an isolated synthetic Gmail batch. Never sends messages."""
import argparse
import base64
import json
import hashlib
import threading
import uuid
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from app import App, ROOT, connect_gmail
from mail_fixtures import CASES


def make_message(case, recipient, run_id):
    key, expected, subject, text = case
    message = EmailMessage()
    message['From'] = 'Mail Agent Autotest <fixture@autotest.invalid>'
    message['To'] = recipient
    message['Subject'] = f'[MA-TEST {run_id}] {subject}'
    message['Date'] = format_datetime(datetime.now(timezone.utc))
    message['Message-ID'] = f'<{run_id}.{key}@autotest.invalid>'
    message['X-Mail-Agent-Test'] = run_id
    message.set_content(text)
    if key == 'work-2':
        message.add_attachment('Отчёт за сентябрь. Проверочный номер 123456.'.encode(), maintype='text', subtype='plain', filename='report-september.txt')
    return message


def run(gmail, endpoint, model, directory, log=print, manifest=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = Path(manifest) if manifest else directory/'manifest.json'
    api = gmail.users()
    recipient = api.getProfile(userId='me').execute()['emailAddress']
    account = hashlib.sha256(recipient.casefold().encode()).hexdigest()
    if manifest.exists():
        state = json.loads(manifest.read_text(encoding='utf-8'))
    else:
        state = {'run_id': datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:8], 'account':account, 'cases': []}
        manifest.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    if state.get('account') != account:
        raise ValueError('Манифест относится к другому Gmail-аккаунту. Выберите новую папку теста.')
    for item in state['cases']:
        message = api.messages().get(userId='me', id=item['id'], format='metadata', metadataHeaders=['X-Mail-Agent-Test']).execute()
        headers = {h['name'].casefold():h['value'] for h in message.get('payload',{}).get('headers',[])}
        if headers.get('x-mail-agent-test') != state['run_id']:
            raise ValueError('Остановлено: сообщение из манифеста не имеет маркера этого теста.')
    if 'label_id' not in state:
        label = api.labels().create(userId='me', body={'name':'AgentTest/'+state['run_id']}).execute()
        state['label_id'] = label['id']
    done = {item['case'] for item in state['cases']}
    for case in CASES:
        if case[0] in done:
            continue
        message = make_message(case, recipient, state['run_id'])
        imported = api.messages().import_(userId='me', neverMarkSpam=True, processForCalendar=False,
            body={'raw':base64.urlsafe_b64encode(message.as_bytes()).decode(), 'labelIds':['INBOX', state['label_id']]}).execute()
        state['cases'].append({'case':case[0], 'expected':case[1], 'id':imported['id']})
        manifest.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        log('Добавлено тестовых писем: '+str(len(state['cases'])))
    app = App.__new__(App)
    app.gmail, app.log, app.stop_sorting = gmail, log, threading.Event()
    app.sort({'limit':'100', 'endpoint':endpoint, 'model':model,
              'folder':str(directory/'attachments'), 'message_ids':[item['id'] for item in state['cases']]})
    labels = {label['id']:label['name'] for label in api.labels().list(userId='me').execute()['labels']}
    results = []
    for item in state['cases']:
        message = api.messages().get(userId='me', id=item['id'], format='metadata', metadataHeaders=['X-Mail-Agent-Test']).execute()
        actual = [labels.get(label, '')[6:] for label in message.get('labelIds', [])
                  if labels.get(label, '').startswith('Agent/') and labels.get(label, '')[6:] in {c[1] for c in CASES}]
        results.append({**item, 'actual':actual, 'passed':actual == [item['expected']]})
    report = {'run_id':state['run_id'], 'total':len(results), 'passed':sum(row['passed'] for row in results), 'results':results}
    (directory/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f"Результат: {report['passed']} из {report['total']}. Отчёт: {directory/'results.json'}")
    return report


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gmail', action='store_true', help='Import synthetic mail into the connected Gmail; otherwise export EML only')
    parser.add_argument('--endpoint', default='http://127.0.0.1:22227/v1')
    parser.add_argument('--model', default='qwen3.5-4b')
    parser.add_argument('--directory', type=Path, default=ROOT/'private'/'gmail-autotest')
    args = parser.parse_args()
    if args.gmail:
        result = run(connect_gmail(), args.endpoint, args.model, args.directory)
        return 0 if result['passed'] == result['total'] else 1
    args.directory.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        (args.directory/(case[0]+'.eml')).write_bytes(make_message(case, 'recipient@example.com', 'preview').as_bytes())
    print('Созданы 18 EML-файлов. Для проверки реального Gmail добавьте --gmail.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
