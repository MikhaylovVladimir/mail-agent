import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from catalog import Catalog
from document_reader import LocalOCR, read_pdf, read_image


def text_pdf(path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=400)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 24 Tf 50 300 Td (Report September 123456) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def sample_image():
    image = Image.new('RGB', (1200, 400), 'white')
    font_path = Path('C:/Windows/Fonts/arial.ttf')
    font = ImageFont.truetype(str(font_path), 44) if font_path.exists() else ImageFont.load_default(size=44)
    ImageDraw.Draw(image).multiline_text((60, 60), 'Отчёт за сентябрь\nInvoice 123456\nСумма: 7500 рублей', font=font, fill='black', spacing=22)
    return image


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_native_pdf_without_ocr(self):
        path = self.root / 'document.pdf'
        text_pdf(path)
        ocr = Mock()
        text, status = read_pdf(path, ocr)
        self.assertIn('September 123456', text)
        ocr.assert_not_called()
        catalog = Catalog(self.root)
        catalog.scan()
        self.assertEqual(len(catalog.search('September 123456')), 1)

    def test_scanned_pdf_rendered_for_ocr(self):
        path = self.root / 'scan.pdf'
        with sample_image() as image:
            image.save(path, 'PDF')
        ocr = Mock(return_value='Отчёт за сентябрь 123456')
        text, status = read_pdf(path, ocr)
        self.assertIn('123456', text)
        self.assertIn('OCR', status)
        ocr.assert_called_once()
        self.assertGreater(ocr.call_args.args[0].width, 100)

    def test_missing_ocr_encrypted_pdf_and_bad_pdf(self):
        path = self.root / 'scan.pdf'
        with sample_image() as image:
            image.save(path, 'PDF')
        text, status = read_pdf(path, None)
        self.assertEqual(text, '')
        self.assertIn('недоступно', status)
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('secret')
        writer.write(self.root / 'locked.pdf')
        self.assertIn('паролем', read_pdf(self.root / 'locked.pdf', None)[1])
        (self.root / 'broken.pdf').write_bytes(b'%PDF-broken')
        catalog = Catalog(self.root)
        catalog.scan()
        self.assertIn('Ошибка', next(r for r in catalog.search() if r['name'] == 'broken.pdf')['status'])

    def test_image_ocr_cache_and_retry_after_failure(self):
        path = self.root / 'picture.png'
        with sample_image() as image:
            image.save(path)
        ocr = Mock(side_effect=RuntimeError('server unavailable'))
        ocr.cache_key = 'test-ocr'
        catalog = Catalog(self.root, ocr=ocr)
        catalog.scan()
        self.assertIn('Ошибка', catalog.search()[0]['status'])
        ocr.side_effect = None
        ocr.return_value = 'Отчёт 123456'
        catalog.scan()
        self.assertEqual(len(catalog.search('123456')), 1)
        catalog.scan()
        self.assertEqual(ocr.call_count, 2)

    def test_ocr_rejects_external_servers(self):
        for endpoint in ('https://example.com/v1', 'http://127.0.0.1.example.com/v1'):
            with self.assertRaises(ValueError):
                LocalOCR(endpoint, 'model')


    def test_mixed_pdf_retains_text_when_scan_ocr_fails(self):
        text_pdf(self.root / 'native.pdf')
        with sample_image() as image:
            image.save(self.root / 'scan.pdf', 'PDF')
        writer = PdfWriter()
        writer.append(self.root / 'native.pdf')
        writer.append(self.root / 'scan.pdf')
        writer.write(self.root / 'mixed.pdf')
        text, status = read_pdf(self.root / 'mixed.pdf', Mock(side_effect=RuntimeError('offline')))
        self.assertIn('September 123456', text)
        self.assertIn('Частично', status)
        self.assertIn('страница 2', status)

    def test_enabling_ocr_reindexes_unchanged_image(self):
        with sample_image() as image:
            image.save(self.root / 'picture.png')
        Catalog(self.root).scan()
        ocr = Mock(return_value='Счёт на оплату 7500')
        ocr.cache_key = 'local-vision'
        catalog = Catalog(self.root, ocr=ocr)
        catalog.scan()
        self.assertEqual(catalog.search('7500')[0]['genre'], 'Счёт')
        ocr.assert_called_once()


@unittest.skipUnless(os.environ.get('MAIL_AGENT_LIVE_TESTS') == '1', 'Vision tests are opt-in')
class VisionIntegrationTests(unittest.TestCase):
    def test_russian_english_and_numbers_in_image_and_scan(self):
        ocr = LocalOCR(os.environ.get('MAIL_AGENT_API', 'http://127.0.0.1:22227/v1'),
                       os.environ.get('MAIL_AGENT_MODEL', 'qwen3.5-4b'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with sample_image() as image:
                image.save(root / 'image.png')
                image.save(root / 'scan.pdf', 'PDF')
            for path in (root / 'image.png', root / 'scan.pdf'):
                with self.subTest(format=path.suffix):
                    text, status = read_image(path, ocr) if path.suffix == '.png' else read_pdf(path, ocr)
                    self.assertIn('123456', text)
                    self.assertIn('7500', text)
                    self.assertIn('сентябрь', text.casefold())
                    self.assertNotIn('Частично', status)


if __name__ == '__main__':
    unittest.main(verbosity=2)
