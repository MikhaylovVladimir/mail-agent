import tempfile
import unittest
import zipfile
from pathlib import Path
from catalog import Catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root)

    def test_search_content_source_and_rescan_no_duplicates(self):
        path = self.root / '1_report.txt'
        path.write_text('Отчёт: выручка за сентябрь 123456', encoding='utf-8')
        self.catalog.record_source(path, {'filename': 'report.txt', 'sender': 'Иван',
                                         'message_id': 'abc123', 'subject': 'Результаты'})
        self.assertEqual(self.catalog.scan(), 1)
        self.catalog.scan()
        rows = self.catalog.search('сентябрь 123456')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['genre'], 'Отчёт')
        self.assertEqual(rows[0]['message_id'], 'abc123')
        self.assertEqual(len(self.catalog.search('Иван')), 1)
        path.write_text('Договор поставки', encoding='utf-8')
        self.catalog.scan()
        self.assertEqual(self.catalog.search('сентябрь'), [])
        self.assertEqual(self.catalog.search('поставки')[0]['genre'], 'Договор')
        path.unlink()
        self.catalog.scan()
        self.assertEqual(self.catalog.search(), [])

    def test_docx_corrupt_and_unsupported_files(self):
        with zipfile.ZipFile(self.root / 'resume.docx', 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="urn:test"><w:p><w:r><w:t>Резюме инженера</w:t></w:r></w:p></w:document>')
        (self.root / 'broken.docx').write_bytes(b'not a zip')
        (self.root / 'archive.bin').write_bytes(b'unsupported')
        self.assertEqual(self.catalog.scan(), 3)
        self.assertEqual(self.catalog.search('инженера')[0]['genre'], 'Резюме')
        rows = {row['name']: row for row in self.catalog.search()}
        self.assertIn('Ошибка чтения', rows['broken.docx']['status'])
        self.assertIn('не поддерживается', rows['archive.bin']['status'])
        self.assertEqual(rows['archive.bin']['message_id'], '')

    def test_storage_boundary(self):
        with self.assertRaises(ValueError):
            self.catalog.file_path('../outside.txt')
        with self.assertRaises(ValueError):
            self.catalog.record_source(self.root.parent / 'outside.txt', {})


if __name__ == '__main__':
    unittest.main()
