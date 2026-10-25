import unittest

from dexp_dock import i18n


class LocaleFilesTest(unittest.TestCase):
    def test_all_locales_define_the_same_keys(self):
        ru = i18n.load_locale('ru')
        en = i18n.load_locale('en')
        self.assertEqual(set(ru), set(en))

    def test_translate_formats_arguments(self):
        tr = i18n.Translator({'greet': 'Hi, {name}'})
        self.assertEqual(tr('greet', name='dock'), 'Hi, dock')

    def test_missing_key_falls_back_to_key(self):
        tr = i18n.Translator({})
        self.assertEqual(tr('no.such.key'), 'no.such.key')

    def test_language_detection_maps_russian(self):
        self.assertEqual(i18n.pick_language('ru_RU'), 'ru')
        self.assertEqual(i18n.pick_language('en_US'), 'en')
        self.assertEqual(i18n.pick_language(None), 'ru')


if __name__ == '__main__':
    unittest.main()
