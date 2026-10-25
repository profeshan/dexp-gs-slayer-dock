import logging
import tempfile
import unittest
from pathlib import Path

from dexp_dock import log


class SetupLoggingTest(unittest.TestCase):
    def test_log_file_is_created_and_receives_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = log.setup_logging(Path(tmp))
            logging.getLogger('dexp_dock.test').info('hello %s', 'dock')
            log.shutdown()
            self.assertEqual(path.parent, Path(tmp))
            self.assertIn('hello dock', path.read_text(encoding='utf-8'))

    def test_unwritable_directory_falls_back(self):
        path = log.setup_logging(Path('Z:/definitely/missing/dir'))
        try:
            self.assertTrue(path.parent.exists())
        finally:
            log.shutdown()


if __name__ == '__main__':
    unittest.main()
