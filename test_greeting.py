import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contacts import Contacts
from app import App
from greeting import compose_body


class GreetingTests(unittest.TestCase):
    def test_untrusted_greetings_are_replaced(self):
        for opening in ('Здравствуйте, Сергей!', 'Добрый день, Иван Петрович!',
                        'Уважаемый Алексей,', 'Пётр, добрый день!', 'Сергей Сергеевич,', 'Доброго дня, Сергей!'):
            with self.subTest(opening=opening):
                self.assertEqual(compose_body(opening+'\n\nОтчёт готов.'), 'Здравствуйте!\n\nОтчёт готов.')

    def test_inline_greeting_and_explicit_salutation(self):
        self.assertEqual(compose_body('Здравствуйте, Сергей! Отчёт готов.', 'Анна Сергеевна'),
                         'Здравствуйте, Анна Сергеевна!\n\nОтчёт готов.')

    def test_body_facts_not_removed_and_english(self):
        self.assertEqual(compose_body('Встреча с Иваном завершилась.'), 'Здравствуйте!\n\nВстреча с Иваном завершилась.')
        self.assertEqual(compose_body('Hello, John! The report is ready.', request='Write a letter'), 'Hello!\n\nThe report is ready.')
        self.assertEqual(compose_body('Спасибо!'), 'Здравствуйте!\n\nСпасибо!')
        self.assertEqual(compose_body('Сообщаю, что отчёт готов.'), 'Здравствуйте!\n\nСообщаю, что отчёт готов.')
        self.assertEqual(compose_body('Уведомляю Вас, что отчёт готов.'), 'Здравствуйте!\n\nУведомляю Вас, что отчёт готов.')
        for verb in ('Информирую', 'Информируем', 'Сообщаем', 'Направляем', 'Прилагаю'):
            with self.subTest(verb=verb):
                text = verb+', что отчёт готов.'
                self.assertEqual(compose_body(text), 'Здравствуйте!\n\n'+text)

    def test_signature_and_empty_body(self):
        self.assertEqual(compose_body('Отчёт готов.\n\nС уважением,\nЧужое Имя'), 'Здравствуйте!\n\nОтчёт готов.')
        with self.assertRaises(ValueError):
            compose_body('Здравствуйте, Иван!')
        with self.assertRaises(ValueError):
            compose_body('Сергей, отчёт готов.')

    def test_existing_contacts_migrate_without_guessing_name(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'contacts.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE contacts(id INTEGER PRIMARY KEY,name TEXT,email TEXT,aliases TEXT)')
                db.execute('INSERT INTO contacts VALUES(1,?,?,?)', ('Тестовый пользователь','test@example.com','[]'))
            db.close()
            contacts=Contacts(path)
            self.assertEqual(contacts.list()[0]['salutation'],'')
            contacts.save('Тестовый пользователь','test@example.com',contact_id=1,salutation='Иван Петрович')
            self.assertEqual(Contacts(path).list()[0]['salutation'],'Иван Петрович')
            with self.assertRaises(ValueError):
                contacts.save('Контакт','x@example.com',salutation='Иван\nBcc: bad')

    def test_history_and_other_contacts_cannot_supply_greeting(self):
        with tempfile.TemporaryDirectory() as folder:
            app=App.__new__(App)
            app.contacts=Contacts(Path(folder)/'contacts.sqlite3')
            app.contacts.save('Тестовый пользователь','test@example.com')
            app.contacts.save('Сергей','other@example.com')
            app.gmail=Mock()
            app.recipient,app.subject,app.body,app.attachments,app.log=Mock(),Mock(),Mock(),Mock(),Mock()
            app.window=Mock()
            app.window.after.side_effect=lambda delay,callback: callback()
            answer=json.dumps(dict(recipient='test@example.com',subject='Отчёт',body='Здравствуйте, Сергей!\n\nОтчёт готов.\nС уважением, Чужое Имя'))
            with patch('app.ask_model',return_value=answer) as model, patch('app.sent_style_samples',return_value=[
                    'Здравствуйте, Сергей!\n\nСпасибо за помощь.\nС уважением, Чужое Имя']):
                app.draft(dict(prompt='Напиши тестовому пользователю, что отчёт готов',recipient='',files=[],use_style=True,endpoint='unused',model='unused'))
            context=json.loads(model.call_args.args[3])
            self.assertEqual(context['contacts'],[])
            self.assertEqual(context['style_examples'],['Спасибо за помощь.'])
            app.body.insert.assert_called_once_with('1.0','Здравствуйте!\n\nОтчёт готов.')
