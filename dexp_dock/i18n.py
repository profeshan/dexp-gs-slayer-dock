"""User-facing strings live in locales/*.json; code refers to them by key only."""
import json
import locale
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent / 'locales'
DEFAULT_LANGUAGE = 'ru'


def load_locale(language):
    with open(LOCALE_DIR / ('%s.json' % language), encoding='utf-8') as f:
        return json.load(f)


def pick_language(locale_name):
    if not locale_name:
        return DEFAULT_LANGUAGE
    return 'ru' if locale_name.lower().startswith('ru') else 'en'


class Translator:
    def __init__(self, messages):
        self.messages = messages

    def __call__(self, key, **kwargs):
        text = self.messages.get(key, key)
        return text.format(**kwargs) if kwargs else text


def system_translator():
    try:
        name = locale.getlocale()[0]
    except ValueError:
        name = None
    return Translator(load_locale(pick_language(name)))
