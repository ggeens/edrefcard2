"""PDF import regression tests using synthetic, non-personal worksheets."""
import importlib.util
from pathlib import Path
import unittest

try:
    import fitz
    AVAILABLE = hasattr(fitz, 'open')
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'PyMuPDF required')
class PdfImportTests(unittest.TestCase):
    def extract(self, fields, vkb=True):
        spec = importlib.util.spec_from_file_location('pdf_import', Path(__file__).resolve().parents[1] / 'www/scripts/pdf_import.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with fitz.open() as doc:
            page = doc.new_page(width=792, height=612)
            page.insert_text((20, 30), 'VKB STECS Test - UntoldForce' if vkb else 'VIRPIL Test')
            for name, rect, value in fields:
                widget = fitz.Widget()
                widget.field_name = name
                widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                widget.rect = fitz.Rect(rect)
                widget.field_value = value
                page.add_widget(widget)
            return module.extract_mapping_from_pdf(doc.tobytes())

    def test_vkb_never_infers_joy_from_numbers(self):
        mapping, jpg = self.extract([
            ('EN1_CW_1', (20, 70, 40, 90), '42'),
            ('EN1_CW_2', (42, 70, 200, 90), 'Personal action'),
            ('Ax_Throttle', (42, 100, 200, 120), ''),
            ('USER1', (20, 150, 200, 170), 'Personal name'),
        ])
        self.assertEqual(len(mapping['boxes']), 2)
        self.assertTrue(mapping['input_verification_required'])
        self.assertTrue(jpg.startswith(b'\xff\xd8'))
        for box in mapping['boxes']:
            self.assertEqual(box['rows'][0]['joy'], '')
            self.assertEqual(box['rows'][0]['verification'], 'unverified')
            self.assertTrue(box['no_chrome'])

    def test_vkb_groups_rows_of_one_control(self):
        mapping, _ = self.extract([
            ('HAT1_1_A', (20, 70, 40, 90), ''),
            ('HAT1_1_B', (42, 70, 200, 90), ''),
            ('HAT1_2_A', (20, 92, 40, 112), ''),
            ('HAT1_2_B', (42, 92, 200, 112), ''),
            ('HAT1_3_A', (20, 114, 40, 134), ''),
            ('HAT1_3_B', (42, 114, 200, 134), ''),
        ])
        self.assertEqual(len(mapping['boxes']), 1)
        self.assertEqual(len(mapping['boxes'][0]['rows']), 3)
        self.assertEqual(mapping['boxes'][0]['physical_group'], 'HAT1')
        self.assertEqual([row['source_row'] for row in mapping['boxes'][0]['rows']], [1, 2, 3])

    def test_virpil_unchanged(self):
        mapping, _ = self.extract([
            ('BTN1_Name', (20, 70, 40, 90), '7'),
            ('BTN1_Desc', (42, 70, 200, 90), ''),
        ], vkb=False)
        self.assertEqual(mapping['boxes'][0]['rows'][0]['joy'], 'Joy_7')
        self.assertNotIn('input_verification_required', mapping)

    def test_rejects_wrong_geometry(self):
        with self.assertRaises(ValueError):
            self.extract([('B1_1', (220, 70, 240, 90), ''),
                          ('B1_2', (42, 70, 200, 90), '')])
