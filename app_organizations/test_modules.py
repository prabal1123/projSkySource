from django.test import SimpleTestCase

from .modules import MODULES, effective_modules


class ModuleRegistryTests(SimpleTestCase):
    def test_requires_point_to_real_modules(self):
        for key, meta in MODULES.items():
            for req in meta["requires"]:
                self.assertIn(req, MODULES, f"{key} requires unknown {req}")

    def test_leave_brings_holidays(self):
        self.assertEqual(effective_modules({"leave"}), {"leave", "holidays"})

    def test_payroll_brings_attendance(self):
        self.assertEqual(effective_modules({"payroll"}), {"payroll", "attendance"})

    def test_nothing_bought_means_nothing_active(self):
        self.assertEqual(effective_modules(set()), set())