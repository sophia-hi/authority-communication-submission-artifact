import unittest

from data_schema import DataRecordError, validate_result_record


class DataSchemaTests(unittest.TestCase):
    def test_missing_record_fields_are_rejected(self):
        with self.assertRaisesRegex(DataRecordError, "missing result field"):
            validate_result_record({}, "complete")


if __name__ == "__main__":
    unittest.main()
