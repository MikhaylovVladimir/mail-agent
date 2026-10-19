"""Compose greetings from an explicit contact field, never from mail history."""
import re


def without_greeting(text):
    text = text.strip()
    # Strip common model/history openers, including an inline following paragraph.
    pattern = (r'^(?:(?:здравствуйте|здравствуй|приветствую|привет|добрый\s+(?:день|вечер)|доброе\s+утро|'
               r'доброго\s+(?:дня|вечера|времени\s+суток)|доброй\s+ночи|'
               r'уважаем(?:ый|ая|ые)|дорог(?:ой|ая|ие)|hello|hi|dear|good\s+(?:morning|afternoon|evening))'
               r'[^\n.!?]*[.!?\n]?\s*)')
    for _ in range(4):
        match = re.match(pattern, text, re.I)
        if match:
            text = text[match.end():].lstrip()
            continue
        # Name before greeting: "Иван, добрый день!".
        match = re.match(r'^[^\n.!?]{1,100},\s*(?:здравствуйте|добрый\s+день|hello)[^\n.!?]*[.!?\n]?\s*', text, re.I)
        if match:
            text = text[match.end():].lstrip()
            continue
        # A standalone address line: "Иван Петрович,".
        match = re.match(r'^(?:[А-ЯЁA-Z][а-яёa-z-]+[ \t]*){1,3},[ \t]*(?:\n|$)\s*', text)
        if match:
            text = text[match.end():].lstrip()
            continue
        break
    return text


def without_signature(text):
    return re.split(r'(?:^|\n)\s*(?:С уважением|С наилучшими пожеланиями|Best regards|Kind regards|Regards)[,!.:\s]',
                    text, maxsplit=1, flags=re.I)[0].strip()


def compose_body(text, salutation='', request=''):
    body = without_signature(without_greeting(text))
    if not body:
        raise ValueError('Модель вернула только приветствие без текста письма. Повторите подготовку.')
    # Fail closed on an unrecognised personal address, rather than keeping a guess.
    address = re.match(r'^((?:[А-ЯЁA-Z][а-яёa-z-]+[ \t]+){0,2}[А-ЯЁA-Z][а-яёa-z-]+),', body)
    prose_openers = {'сообщаю', 'подтверждаю', 'уведомляю', 'пожалуйста', 'коллеги', 'друзья',
                     'напоминаю', 'отмечу', 'благодарю', 'спасибо', 'надеюсь', 'считаю',
                     'уточняю', 'направляю', 'пишу', 'прошу', 'просим', 'полагаю', 'заранее',
                     'действительно', 'итак', 'кстати', 'please', 'firstly', 'finally'}
    first_word = address.group(1).split()[0].casefold() if address else ''
    prose_verb = re.match(r'^(?:информир|сообщ|уведомл|направл|подтвержд|прилаг|напомина|обраща|благодар)', first_word)
    if address and first_word not in prose_openers and not prose_verb:
        raise ValueError('Модель добавила неподтверждённое обращение. Повторите подготовку без имени.')
    russian = not request or bool(re.search('[а-яё]', request, re.I))
    greeting = ('Здравствуйте' if russian else 'Hello') + (', '+salutation if salutation else '') + '!'
    return greeting+'\n\n'+body
