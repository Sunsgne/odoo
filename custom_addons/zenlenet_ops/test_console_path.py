import unittest

from console_path import console_path


class ConsolePathTests(unittest.TestCase):
    def test_legacy_client_path(self):
        self.assertEqual(console_path('/odoo'), '/obss')
        self.assertEqual(console_path('/odoo/contacts/3'), '/obss/contacts/3')
        self.assertEqual(console_path('/odoo?debug=1'), '/obss?debug=1')

    def test_bare_web_entry(self):
        self.assertEqual(console_path('/web'), '/obss')
        self.assertEqual(console_path('/web?debug=1'), '/obss?debug=1')

    def test_other_paths_stay(self):
        self.assertEqual(console_path('/web/login'), '/web/login')
        self.assertEqual(console_path('/web/assets/x'), '/web/assets/x')
        self.assertEqual(console_path('/my'), '/my')
        self.assertEqual(console_path('/obss/contacts'), '/obss/contacts')
        self.assertIsNone(console_path(None))


if __name__ == '__main__':
    unittest.main()
