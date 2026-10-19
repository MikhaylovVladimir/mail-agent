"""Resumable synthetic functional benchmark. Gmail operations target own account only."""
import argparse
import base64
import difflib
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch
from app import App, ROOT, connect_gmail
from catalog import Catalog, extract_text
from contacts import Contacts, request_recipient
from document_reader import LocalOCR
from voice import cached_model, transcribe
from benchmark_cases import mail_cases, VOICE_PHRASES
from gmail_autotest import run as gmail_run
from attachment_picker import available, attachment_name


def dump(path, value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def normalized(text):
    return ' '.join(re.findall(r'[а-яa-z0-9]+',text.casefold().replace('ё','е')))


def distance(first,second):
    previous=list(range(len(second)+1))
    for i,a in enumerate(first,1):
        current=[i]
        for j,b in enumerate(second,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=current
    return previous[-1]


def fixtures(root):
    from PIL import Image,ImageDraw,ImageFont,ImageFilter
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    folder=root/'documents'
    folder.mkdir(exist_ok=True)
    font_path=Path('C:/Windows/Fonts/arial.ttf')
    pdfmetrics.registerFont(TTFont('BenchArial',str(font_path)))
    manifest=[]
    for i in range(10):
        token=str(123400+i)
        amount=str(7500+i*100)
        lines=['Отчёт за сентябрь',f'Номер: {token}',f'Сумма: {amount} рублей']
        native=folder/f'native-{i:02}.pdf'
        pdf=canvas.Canvas(str(native),pagesize=(600,300))
        pdf.setFont('BenchArial',20)
        for line,y in zip(lines,[240,200,160]):
            pdf.drawString(40,y,line)
        pdf.save()
        image=Image.new('RGB',(1200,400),'white')
        font=ImageFont.truetype(str(font_path),[32,38,44,50,56][i%5])
        ImageDraw.Draw(image).multiline_text((60,55),'\n'.join(lines),font=font,fill='black',spacing=18)
        if i>=5:
            image=image.rotate([1,-1,2,-2,1][i-5],fillcolor='white',resample=Image.Resampling.BICUBIC)
        picture=folder/f'picture-{i:02}.png'
        scan=folder/f'scan-{i:02}.pdf'
        image.save(picture)
        image.save(scan,'PDF',resolution=144)
        image.close()
        for path,kind in [(native,'native_pdf'),(picture,'image_ocr'),(scan,'scanned_pdf_ocr')]:
            manifest.append(dict(path=str(path),kind=kind,expected='\n'.join(lines),fields=[token,amount,'сентябрь']))
    dump(root/'fixtures.json',manifest)
    print('Созданы 30 документов: 10 PDF с текстом, 10 картинок, 10 PDF-сканов.',flush=True)
    return manifest


def summarize(rows):
    return dict(total=len(rows),passed=sum(bool(row.get('passed')) for row in rows),
                failed=sum(not bool(row.get('passed')) for row in rows),cases=rows)


def document_tests(root,endpoint,model):
    manifest=json.loads((root/'fixtures.json').read_text(encoding='utf-8'))
    result_path=root/'documents-results.json'
    rows=json.loads(result_path.read_text(encoding='utf-8'))['cases'] if result_path.exists() else []
    done={row['case'] for row in rows}
    ocr=LocalOCR(endpoint,model)
    for i,item in enumerate(manifest):
        if i in done:
            continue
        started=time.perf_counter()
        try:
            text,status=extract_text(Path(item['path']),ocr)
            actual=normalized(text)
            checks={field:normalized(field) in actual for field in item['fields']}
            row=dict(case=i,kind=item['kind'],passed=all(checks.values()),fields=checks,status=status,
                     actual=text,expected=item['expected'])
        except Exception as error:
            row=dict(case=i,kind=item['kind'],passed=False,error=str(error))
        row['seconds']=time.perf_counter()-started
        rows.append(row)
        dump(result_path,summarize(rows))
        print(f"Документы {len(rows)}/30: {row['passed']}",flush=True)
    return summarize(rows)


def voice_tests(root):
    from faster_whisper.audio import decode_audio
    folder=root/'voice'
    folder.mkdir(exist_ok=True)
    result_path=root/'voice-results.json'
    rows=json.loads(result_path.read_text(encoding='utf-8'))['cases'] if result_path.exists() else []
    done={row['case'] for row in rows}
    # Generate TTS independently from Whisper; two installed voices/rates are not assumed.
    for i,phrase in enumerate(VOICE_PHRASES):
        if i in done:
            continue
        path=folder/f'phrase-{i:02}.wav'
        script=("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.SelectVoice('Microsoft Irina Desktop'); $s.Rate="+str([-1,0,1][i%3])+"; "
                "$s.SetOutputToWaveFile('"+str(path.resolve()).replace("'","''")+"'); $s.Speak('"+phrase.replace("'","''")+"'); $s.Dispose()")
        started=time.perf_counter()
        try:
            subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],check=True,capture_output=True,timeout=30)
            audio=decode_audio(str(path),sampling_rate=16000)
            text=transcribe(audio,cached_model())
            expected,actual=normalized(phrase),normalized(text)
            edits=distance(expected.split(),actual.split())
            row=dict(case=i,expected=phrase,actual=text,passed=expected==actual,word_edits=edits,
                     reference_words=len(expected.split()),wer=edits/max(1,len(expected.split())),
                     cer=distance(expected,actual)/max(1,len(expected)),audio_seconds=len(audio)/16000)
        except Exception as error:
            row=dict(case=i,expected=phrase,passed=False,error=str(error))
        row['seconds']=time.perf_counter()-started
        rows.append(row)
        report=summarize(rows)
        report['aggregate_wer']=sum(r.get('word_edits',0) for r in rows)/max(1,sum(r.get('reference_words',0) for r in rows))
        report['note']='Synthetic Russian TTS; not microphone speech or a representative ASR dataset.'
        dump(result_path,report)
        print(f"Речь {len(rows)}/30: WER={row.get('wer','error')}",flush=True)
    return json.loads(result_path.read_text(encoding='utf-8'))


def make_app(root):
    app=App.__new__(App)
    app.contacts=Contacts(root/'synthetic-contacts.sqlite3')
    app.gmail=None
    for i in range(30):
        name=f'Контакт номер {i}'
        if not any(row['name']==name for row in app.contacts.list()):
            app.contacts.save(name,f'person{i}@example.com',salutation='' if i%2 else 'Иван Петрович')
    app.recipient,app.subject,app.body,app.attachments,app.log=Mock(),Mock(),Mock(),Mock(),Mock()
    app.window=Mock()
    app.window.after.side_effect=lambda delay,callback:callback()
    return app


def draft_tests(root,endpoint,model):
    folder=root/'draft-files'
    folder.mkdir(exist_ok=True)
    app=make_app(root)
    result_path=root/'draft-results.json'
    rows=json.loads(result_path.read_text(encoding='utf-8'))['cases'] if result_path.exists() else []
    done={row['case'] for row in rows}
    for i in range(30):
        if i in done:
            continue
        path=folder/f'report-{i}.txt'
        path.write_text(f'Отчёт за сентябрь. Код {8000+i}.',encoding='utf-8')
        request=f'Напиши контакту номер {i}, что отчёт за сентябрь готов. Без подписи.'
        started=time.perf_counter()
        try:
            with patch('app.sent_style_samples',return_value=['Здравствуйте, Чужоеимя!\n\nСпасибо за ответ.\nС уважением, Староеимя']):
                app.draft(dict(prompt=request,recipient='',files=[str(path)],folder=str(folder),endpoint=endpoint,model=model,use_style=bool(i%3==0)))
            actual=app.recipient.set.call_args.args[0]
            body=app.body.insert.call_args.args[1]
            expected_greeting='Здравствуйте!' if i%2 else 'Здравствуйте, Иван Петрович!'
            checks=dict(recipient=actual==f'person{i}@example.com',greeting=body.startswith(expected_greeting),
                        no_old_names='Чужоеимя' not in body and 'Староеимя' not in body,
                        attachment=app.files==[str(path.resolve())],nonempty_body=bool(body.split('\n\n')[-1].strip()),
                        report_fact=bool(re.search('отч[её]т',body,re.I)))
            row=dict(case=i,passed=all(checks.values()),checks=checks,body=body)
        except Exception as error:
            row=dict(case=i,passed=False,error=str(error))
        row['seconds']=time.perf_counter()-started
        rows.append(row)
        dump(result_path,summarize(rows))
        print(f"Черновики {len(rows)}/30: {row['passed']}",flush=True)
    return summarize(rows)


def operation_tests(root):
    folder=root/'picker-files'
    folder.mkdir(exist_ok=True)
    catalog=Catalog(folder)
    rows=[]
    for i in range(30):
        sub=folder/f'opaque-message-{i:02}'
        sub.mkdir(exist_ok=True)
        path=sub/'0_internal.txt'
        text=f'Отчёт за сентябрь. Код QX{i:04}.'
        path.write_text(text,encoding='utf-8')
        catalog.record_source(path,dict(filename=f'Отчёт QX{i:04}.txt',sender=f'Синтетический отправитель {i}',subject=f'Рабочая задача {i}',date='2026-10-19'))
    catalog.scan()
    app=make_app(root)
    for i in range(30):
        matches=available(folder,f'QX{i:04}')
        chosen=matches[0] if len(matches)==1 else None
        checks=dict(picker_unique=len(matches)==1,picker_original=bool(chosen and chosen['name']==f'Отчёт QX{i:04}.txt'),
                    catalog_search=len(catalog.search(f'QX{i:04}'))==1,
                    contact=request_recipient(app.contacts,f'Напиши контакту номер {i}')==f'person{i}@example.com')
        rows.append(dict(case=i,passed=all(checks.values()),checks=checks))
    report=summarize(rows)
    dump(root/'operations-results.json',report)
    return report


def boundary_tests(root):
    from contacts import valid_email,validate_draft
    from attachment_selection import check_files,select_attachments
    from greeting import compose_body
    from app import ask_model
    import numpy as np
    folder=root/'boundary-files'
    folder.mkdir(exist_ok=True)
    (folder/'.secret').write_text('hidden')
    (folder/'same-one.txt').write_text('same')
    (folder/'same-two.txt').write_text('same')
    store=make_app(root).contacts
    catalog=Catalog(folder)
    catalog.scan()
    checks=[]
    bad_emails=['','bad','a@localhost','.a@example.com','a..b@example.com','a@-example.com',
                'a@example..com','a@example.com\nBcc: x@y.com','x'*65+'@example.com','a@example.com,b@example.com']
    for i,email in enumerate(bad_emails):
        checks.append((f'email-{i}',lambda value=email:not valid_email(value)))
    def rejected(action):
        try:
            action()
        except ValueError:
            return True
        return False
    for i,path in enumerate([folder/'.secret',folder/'../outside.txt',folder,folder/'missing.txt',root/'synthetic-contacts.sqlite3']):
        checks.append((f'file-{i}',lambda value=path:rejected(lambda:check_files(folder,[value]))))
    for i,value in enumerate(['not-json','{}',json.dumps(dict(recipient='person1@example.com',subject='Тема',body='Текст')),
                              json.dumps(dict(recipient='person0@example.com',subject='Тема\nBcc: x',body='Текст')),
                              json.dumps(dict(recipient='person0@example.com',subject='Тема',body='Текст',attachment_queries=['x']*11))]):
        checks.append((f'draft-{i}',lambda value=value:rejected(lambda:validate_draft(value,store,'Напиши контакту номер 0'))))
    checks.extend([
        ('search-missing',lambda:rejected(lambda:select_attachments(catalog,['absenttoken']))),
        ('search-ambiguous',lambda:rejected(lambda:select_attachments(catalog,['same']))),
        ('search-hidden',lambda:rejected(lambda:select_attachments(catalog,[],[folder/'.secret']))),
    ])
    for i,audio in enumerate([np.zeros(16000),np.full(16000,np.nan),np.ones(5)*.1]):
        checks.append((f'audio-{i}',lambda value=audio:rejected(lambda:transcribe(value,cached_model()))))
    checks.extend([
        ('greeting-empty',lambda:rejected(lambda:compose_body('Здравствуйте!'))),
        ('greeting-name',lambda:rejected(lambda:compose_body('Сергей, отчёт готов.'))),
        ('external-http',lambda:rejected(lambda:ask_model('http://example.com/v1','x','s','p'))),
        ('external-https',lambda:rejected(lambda:ask_model('https://example.com/v1','x','s','p'))),
    ])
    rows=[]
    for key,check in checks:
        try:
            rows.append(dict(case=key,passed=bool(check()),expected='reject invalid input'))
        except Exception as error:
            rows.append(dict(case=key,passed=False,error=str(error)))
    report=summarize(rows)
    dump(root/'boundary-results.json',report)
    print(f"Граничные случаи: {report['passed']}/{report['total']}",flush=True)
    return report


def delivery_tests(root,gmail):
    # Never allow a model, contact or CLI argument to choose the actual destination.
    own=gmail.users().getProfile(userId='me').execute()['emailAddress']
    folder=root/'send-files'
    folder.mkdir(exist_ok=True)
    result_path=root/'delivery-results.json'
    rows=json.loads(result_path.read_text(encoding='utf-8'))['cases'] if result_path.exists() else []
    done={row['case'] for row in rows}
    run_id=root.name
    for i in range(30):
        if i in done:
            continue
        path=folder/f'attachment-{i:02}.txt'
        data=f'Синтетическое вложение {i}. Проверочный код {9000+i}.'.encode()
        path.write_bytes(data)
        subject=f'[MA-DELIVERY {run_id}] Проверка {i:02}'
        body=f'Здравствуйте!\n\nЭто разрешённая проверка отправки самому себе. Код {9000+i}.'
        row=dict(case=i,passed=False,state='started',recipient='connected-account-only')
        rows.append(row)
        dump(result_path,summarize(rows))  # Never silently retry uncertain sends on resume.
        started=time.perf_counter()
        try:
            app=App.__new__(App)
            app.gmail,app.log=gmail,Mock()
            app.contacts=Contacts(root/'delivery-contacts.sqlite3')
            app.recipient,app.subject,app.body=Mock(),Mock(),Mock()
            app.recipient.get.return_value=own
            app.subject.get.return_value=subject
            app.body.get.return_value=body
            app.files=[str(path)]
            app.run=lambda action:action({'folder':str(folder)})
            with patch('app.messagebox.askyesno',return_value=True):
                sent=app.send()
            row['send_id']=sent['id']
            row['state']='accepted'
            dump(result_path,summarize(rows))
            raw=gmail.users().messages().get(userId='me',id=sent['id'],format='raw').execute()
            message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw['raw']))
            message_id=message['Message-ID']
            delivered=[]
            for attempt in range(8):
                delivered=gmail.users().messages().list(userId='me',q='in:inbox rfc822msgid:'+message_id,maxResults=2).execute().get('messages',[])
                if delivered:
                    break
                time.sleep(1)
            if delivered:
                received=gmail.users().messages().get(userId='me',id=delivered[0]['id'],format='raw').execute()
                message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(received['raw']))
            checks=dict(accepted=bool(sent['id']),inbox=bool(delivered),to_self=str(message['To']).casefold()==own.casefold(),
                        subject=str(message['Subject'])==subject,
                        body=str(9000+i) in message.get_body(preferencelist=('plain',)).get_content())
            attachments=list(message.iter_attachments())
            checks['attachment_hash']=len(attachments)==1 and hashlib.sha256(attachments[0].get_payload(decode=True)).digest()==hashlib.sha256(data).digest()
            row.update(checks=checks,passed=all(checks.values()),state='verified')
        except Exception as error:
            row.update(error=str(error),state='uncertain_or_failed')
        row['seconds']=time.perf_counter()-started
        dump(result_path,summarize(rows))
        print(f"Отправка самому себе {len(rows)}/30: {row['passed']}",flush=True)
    return summarize(rows)


def verify_delivery(root,gmail):
    """Read the actual inbox copy, including attachment bytes; never resend."""
    own=gmail.users().getProfile(userId='me').execute()['emailAddress']
    result_path=root/'delivery-results.json'
    report=json.loads(result_path.read_text(encoding='utf-8'))
    for row in report['cases']:
        try:
            source=gmail.users().messages().get(userId='me',id=row['send_id'],format='raw').execute()
            original=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(source['raw']))
            copies=gmail.users().messages().list(userId='me',q='in:inbox rfc822msgid:'+original['Message-ID'],maxResults=2).execute().get('messages',[])
            if not copies:
                raise ValueError('Inbox copy not found')
            raw=gmail.users().messages().get(userId='me',id=copies[0]['id'],format='raw').execute()
            message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw['raw']))
            attachments=list(message.iter_attachments())
            expected=(root/'send-files'/f"attachment-{row['case']:02}.txt").read_bytes()
            checks=dict(inbox=True,to_self=str(message['To']).casefold()==own.casefold(),
                        body=str(9000+row['case']) in message.get_body(preferencelist=('plain',)).get_content(),
                        subject=str(message['Subject'])==str(original['Subject']),
                        attachment_hash=len(attachments)==1 and hashlib.sha256(attachments[0].get_payload(decode=True)).digest()==hashlib.sha256(expected).digest())
            row.update(received_checks=checks,passed=all(checks.values()),state='inbox_bytes_verified')
        except Exception as error:
            row.update(passed=False,verification_error=str(error))
        dump(result_path,summarize(report['cases']))
        print(f"Проверка входящей копии {row['case']+1}/30: {row['passed']}",flush=True)
    return summarize(report['cases'])


def export_summary(root):
    mail=json.loads((root/'mail/results.json').read_text(encoding='utf-8'))
    voice=json.loads((root/'voice-results.json').read_text(encoding='utf-8'))
    categories=sorted({row['expected'] for row in mail['results']})
    f1=[]
    per_category=[]
    for name in categories:
        tp=sum(row['expected']==name and row['actual']==[name] for row in mail['results'])
        fp=sum(row['expected']!=name and name in row['actual'] for row in mail['results'])
        fn=sum(row['expected']==name and row['actual']!=[name] for row in mail['results'])
        score=2*tp/max(1,2*tp+fp+fn)
        f1.append(score)
        per_category.append(dict(category=name,tp=tp,fp=fp,fn=fn,f1=score))
    metrics=[('Классификация Gmail',mail['passed'],mail['total'],'Совпадение с ожидаемой категорией')]
    for filename,title,criterion in [
        ('documents-results.json','PDF и изображения','Номер, сумма и месяц присутствуют в извлечённом тексте'),
        ('draft-results.json','Черновики','Адресат, приветствие, отсутствие имён из истории, вложение и факт об отчёте'),
        ('operations-results.json','Контакты, каталог и выбор файлов','Каждый из четырёх критериев проверен на 30 случаях'),
        ('boundary-results.json','Граничные случаи','Неверные входные данные отклонены'),
        ('delivery-results.json','Отправка самому себе','Gmail принял письмо, найдена входящая копия, адрес/текст/вложение совпали')]:
        report=json.loads((root/filename).read_text(encoding='utf-8'))
        metrics.append((title,report['passed'],report['total'],criterion))
    metrics.append(('Речь: точное совпадение',voice['passed'],voice['total'],'Сравнение нормализованных слов; пунктуация, регистр и е/ё не учитываются'))
    run_date=datetime.strptime(mail['run_id'][:8],'%Y%m%d').date().isoformat()
    import platform
    import importlib.metadata
    environment=dict(python=platform.python_version(),faster_whisper=importlib.metadata.version('faster-whisper'),
                     ctranslate2=importlib.metadata.version('ctranslate2'))
    summary=dict(date=run_date,environment=environment,metrics=[dict(operation=a,passed=b,total=c,criterion=d) for a,b,c,d in metrics],
                 macro_f1=sum(f1)/len(f1),per_category=per_category,voice_wer=voice['aggregate_wer'],
                 limitations=['Synthetic corpus, not held-out after rule tuning','Synthetic TTS, not real microphone audio',
                              'OCR success checks fields, not full-text CER','Sending to self does not test delivery to other providers'])
    dump(root/'summary.json',summary)
    baseline_path=root/'mail/results-before-reclassify.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else None
    baseline_note=(f"Первый прогон: {baseline['passed']}/{baseline['total']}; после уточнения правил повторён тот же набор. " if baseline else '')
    lines=['# Результаты функционального прогона','', f'Дата набора: {run_date}. Все данные синтетические.',
           'Gmail, LM Studio и Whisper проверены реально; отправка разрешена только подключённому аккаунту.',
           '', '| Операция | Успех | Доля | Критерий |','|---|---:|---:|---|']
    for title,passed,total,criterion in metrics:
        lines.append(f'| {title} | {passed}/{total} | {passed/total:.1%} | {criterion} |')
    lines+=['',f"Macro-F1 классификации: {summary['macro_f1']:.4f}.",
            f"WER речи: {voice['aggregate_wer']:.2%} (редакционное расстояние слов / число эталонных слов).",'',
            '## Категории','', '| Категория | TP | FP | FN | F1 |','|---|---:|---:|---:|---:|']
    for row in per_category:
        lines.append(f"| {row['category']} | {row['tp']} | {row['fp']} | {row['fn']} | {row['f1']:.4f} |")
    lines+=['','## Методика и ограничения','',
            '- 90 уникальных писем: по 10 на 9 категорий. Импорт через Gmail API проверяет обработку, не SMTP-доставку.',
            '- '+baseline_note+'Корпус известен разработчикам. Итог не является независимой оценкой после настройки.',
            '- Документы: 10 PDF с текстовым слоем, 10 PNG, 10 сканированных PDF. Шрифт 32–56 px, часть сканов повёрнута на 1–2 градуса. Рукописи и сложные таблицы здесь не представлены.',
            '- Для речи использован Windows TTS Microsoft Irina с тремя скоростями и локальный faster-whisper-small, CPU/int8. Проверки реального микрофона этим не заменяются.',
            '- 30 черновиков используют вымышленные контакты, локальную модель и существующие TXT-вложения; семантическое качество всего текста человеком не оценивалось.',
            '- 30 отправок выполнены самому себе. Проверены входящая копия по Message-ID, текст и SHA-256 вложения. Доставка другим провайдерам не проверялась.',
            '- Неопределённые отправки автоматически не повторяются. Известные сбои текущего прогона отдельно описаны в TESTING.md.',
            '- Дополнительно доступны обычные и интеграционные unittest-проверки. Они не заменяют ручную приёмку UI.',
            '- Полные JSON-результаты, сообщения и WAV находятся в private/benchmark-20261019 и не публикуются. В этом отчёте нет адреса пользователя или ID его сообщений.',
            f"- Среда отчёта: Python {environment['python']}, faster-whisper {environment['faster_whisper']}, CTranslate2 {environment['ctranslate2']}; распознавание речи CPU/int8, два потока. Показатели скорости здесь не заявляются.",
            '', '## Воспроизведение','',
            'Установите requirements-dev.txt. `python functional_benchmark.py --phase all --directory private/your-run` создаёт файлы, импортирует 90 писем и отправляет 30 писем только подключённому аккаунту. Нужны Gmail OAuth, LM Studio и локальный Whisper; TTS требует Windows и голос Microsoft Irina.',
            'Каждая фаза доступна отдельно. Результаты записываются после каждого случая. Повтор продолжает запуск, не повторяя уже записанные отправки. `--reclassify` разрешён только для отмеченного синтетического набора.', '']
    (ROOT/'BENCHMARK_RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({key:value for key,value in summary.items() if key not in ('per_category','limitations')},ensure_ascii=False,indent=2),flush=True)
    return summary


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['fixtures','mail','documents','voice','drafts','operations','boundaries','delivery','delivery-check','summary','all'],required=True)
    parser.add_argument('--directory',type=Path,default=ROOT/'private'/'benchmark-20261019')
    parser.add_argument('--endpoint',default='http://127.0.0.1:22227/v1')
    parser.add_argument('--model',default='qwen3.5-4b')
    parser.add_argument('--reclassify',action='store_true',help='Reset processed markers on this synthetic batch only')
    args=parser.parse_args()
    root=args.directory.resolve()
    root.mkdir(parents=True,exist_ok=True)
    phases=['fixtures','mail','documents','voice','drafts','operations','boundaries','delivery','summary'] if args.phase=='all' else [args.phase]
    for phase in phases:
        if phase=='fixtures':
            fixtures(root)
        elif phase=='mail':
            if args.reclassify and (root/'mail'/'results.json').exists() and not (root/'mail'/'results-before-reclassify.json').exists():
                import shutil
                shutil.copy2(root/'mail'/'results.json',root/'mail'/'results-before-reclassify.json')
            gmail_run(connect_gmail(),args.endpoint,args.model,root/'mail',cases=mail_cases(),reclassify=args.reclassify)
        elif phase=='documents':
            document_tests(root,args.endpoint,args.model)
        elif phase=='voice':
            voice_tests(root)
        elif phase=='drafts':
            draft_tests(root,args.endpoint,args.model)
        elif phase=='operations':
            operation_tests(root)
        elif phase=='boundaries':
            boundary_tests(root)
        elif phase=='delivery':
            delivery_tests(root,connect_gmail())
        elif phase=='delivery-check':
            verify_delivery(root,connect_gmail())
        elif phase=='summary':
            export_summary(root)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
