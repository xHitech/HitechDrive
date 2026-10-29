"""The shared UI demo must be reproducible and contain only synthetic fixture data."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent

class OfflineDemoTests(unittest.TestCase):
    def test_demo_matches_public_ui_and_fixture(self):
        spec=importlib.util.spec_from_file_location('generate_demo',ROOT/'tools/gerar-demo.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual((ROOT/'docs/demo.html').read_text(),module.build())
        self.assertNotIn('<script src=',module.build())
        self.assertIn('OFFLINE DEMO',module.build())
