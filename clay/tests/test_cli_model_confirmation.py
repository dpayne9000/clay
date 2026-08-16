"""Tests for the model-mismatch confirmation shown before command work."""

import io
import unittest
from unittest.mock import patch

from clay.cli import _confirm_model_mismatch


class ModelConfirmationTest(unittest.TestCase):

    def test_yes_continues(self):
        with patch('builtins.input', return_value='yes'), \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertTrue(_confirm_model_mismatch('model mismatch'))
        self.assertIn('clay: model mismatch', stderr.getvalue())

    def test_no_and_end_of_input_stop(self):
        for response in ('n', ''):
            with self.subTest(response=response), \
                    patch('builtins.input', return_value=response), \
                    patch('sys.stderr', new_callable=io.StringIO):
                self.assertFalse(_confirm_model_mismatch('model mismatch'))

        with patch('builtins.input', side_effect=EOFError), \
                patch('sys.stderr', new_callable=io.StringIO):
            self.assertFalse(_confirm_model_mismatch('model mismatch'))


if __name__ == '__main__':
    unittest.main()
