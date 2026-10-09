import tempfile
import unittest
from pathlib import Path
from attachment_selection import select_attachments, check_files, attachment_requested
from catalog import Catalog


class AttachmentSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'report.txt'
        self.path.write_text('Отчёт за сентябрь 7500', encoding='utf-8')
        self.catalog = Catalog(self.root)
        self.catalog.scan()

    def test_match_by_content_and_yo_normalization(self):
        self.assertEqual(select_attachments(self.catalog, ['отчет сентябрь']), [str(self.path)])

    def test_multiple_and_missing_files_require_clarification(self):
        (self.root / 'other.txt').write_text('Отчёт сентябрь 9000', encoding='utf-8')
        self.catalog.scan()
        with self.assertRaisesRegex(ValueError, 'найдено 2'):
            select_attachments(self.catalog, ['отчет сентябрь'])
        with self.assertRaisesRegex(ValueError, 'Не найден'):
            select_attachments(self.catalog, ['неизвестный'])

    def test_manual_choice_priority_and_deduplication(self):
        self.assertEqual(select_attachments(self.catalog, ['неизвестный'], [self.path, self.path]), [str(self.path)])
        self.assertEqual(select_attachments(self.catalog, ['отчет', 'сентябрь']), [str(self.path)])

    def test_removed_external_and_service_files_rejected(self):
        with self.assertRaises(ValueError):
            check_files(self.root, [self.root.parent / 'external.txt'])
        with self.assertRaises(ValueError):
            check_files(self.root, [self.catalog.db])
        self.path.unlink()
        with self.assertRaises(ValueError):
            select_attachments(self.catalog, ['отчет'])

    def test_explicit_attachment_request_recognized(self):
        self.assertTrue(attachment_requested('Приложи отчёт'))
        self.assertTrue(attachment_requested('Нужно прикрепить файл'))
        self.assertFalse(attachment_requested('Отчёт готов'))


if __name__ == '__main__':
    unittest.main()
