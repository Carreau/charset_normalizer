"""
Free-threading specific test
"""
from __future__ import annotations

import unittest
import sys
import sysconfig
import charset_normalizer.md


class TestFreeThreading(unittest.TestCase):
    def test_do_no_reenable_gil(self):
        if sys.version_info > (3, 14):
            is_freethreaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
            if is_freethreaded:
                assert sys._is_gil_enabled() is False
