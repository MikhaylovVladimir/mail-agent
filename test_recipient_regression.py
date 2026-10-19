import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import test_interface
from contacts import request_recipient, validate_draft


class RecipientRegressionTests(unittest.TestCase):
    setUp = test_interface.InterfaceTests.setUp
    tearDown = test_interface.InterfaceTests.tearDown

    def test_resolve_inflected_user_and_wrong_known_contact(self):
        self.app.contacts.save('Тестовый пользователь','test@example.com')
        self.app.contacts.save('Другой контакт','other@example.com')
        request = 'Напиши тестовому пользователю, что отчет готов и приложи отчет за сентябрь.'
        self.assertEqual(request_recipient(self.app.contacts, request), 'test@example.com')
        answer = json.dumps(dict(recipient='other@example.com',subject='Отчёт',body='Готово'))
        with self.assertRaisesRegex(ValueError,'другого получателя'):
            validate_draft(answer,self.app.contacts,request)


    def test_new_letter_same_request_manual_attachment_wrong_model_address(self):
        self.app.contacts.save('Тестовый пользователь','test@example.com')
        self.app.contacts.save('Другой контакт','other@example.com')
        path = Path(self.temp.name)/'report.txt'
        path.write_text('Отчёт за сентябрь',encoding='utf-8')
        request = 'Напиши тестовому пользователю, что отчет готов и приложи отчет за сентябрь.'
        answer = json.dumps(dict(recipient='other@example.com',subject='Отчёт',body='Готово',attachment_queries=[]))
        with patch('app.ask_model',return_value=answer) as model:
            for _ in range(3):
                with patch('app.messagebox.askyesno',return_value=True):
                    self.app.new_letter()
                self.app.prompt.insert('1.0',request)
                self.app.files=[str(path)]
                self.app.draft(dict(prompt=request,recipient='',files=[str(path)],endpoint='unused',model='unused',folder=self.temp.name))
                self.app.pump_ui()
                self.assertEqual(self.app.recipient.get(),'test@example.com')
                self.assertEqual(json.loads(model.call_args.args[3])['recipient_override'],'test@example.com')


    def test_generated_address_not_reused_as_manual_override(self):
        self.app.generated_recipient('old@example.com')
        self.app.prompt.insert('1.0','Напиши тестовому пользователю')
        with patch('app.threading.Thread') as worker:
            self.app.run(self.app.draft)
            target=worker.call_args.kwargs['target']
            with patch.object(self.app,'contacts') as contacts, patch('app.request_recipient',return_value='test@example.com'), patch('app.ask_model',side_effect=ValueError('stop')):
                contacts.resolve.return_value='test@example.com'
                target()
                contacts.resolve.assert_called_with('test@example.com')
        self.app.pump_ui()


    def test_manual_selection_remains_explicit(self):
        self.app.generated_recipient('old@example.com')
        self.app.recipient.set('manual@example.com')
        self.assertEqual(self.app.recipient_origin,'manual')


    def test_ambiguous_or_unknown_request_never_chooses_random_contact(self):
        self.app.contacts.save('Тестовый пользователь','one@example.com')
        self.app.contacts.save('Тестовый пользователь','two@example.com')
        with self.assertRaises(ValueError):
            request_recipient(self.app.contacts,'Напиши тестовому пользователю')
        answer=json.dumps(dict(recipient='one@example.com',subject='Тема',body='Текст'))
        with self.assertRaises(ValueError):
            validate_draft(answer,self.app.contacts,'Напиши неизвестному человеку')

