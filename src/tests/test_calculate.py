import unittest
from unittest.mock import patch

from calculate import evaluate_batch, evaluate_expression


class CalculateTests(unittest.TestCase):
    def test_arithmetic_and_parentheses(self):
        result = evaluate_batch([
            "2 + 3 * 4", "(10 - 2) / 4", "2 ** 3",
            "min(8, 9)", "max(8, 9)",
        ])
        self.assertTrue(result["accepted"])
        self.assertEqual(
            [row["value"] for row in result["results"]],
            [14.0, 2.0, 8.0, 8.0, 9.0])

    def test_calculator_has_no_names_files_or_code_execution(self):
        for expression in (
                "branch_1_profit + branch_2_profit",
                "__import__('os').getcwd()",
                "open('/tmp/x')"):
            with self.subTest(expression=expression):
                self.assertFalse(evaluate_expression(expression)["accepted"])

    def test_wrong_or_incomplete_expression_is_not_corrected(self):
        partial = evaluate_expression("52 * 1.088")
        full = evaluate_expression("52 * 1.088 * 0.918")
        self.assertTrue(partial["accepted"])
        self.assertTrue(full["accepted"])
        self.assertNotEqual(partial["value"], full["value"])

    def test_percent_is_rejected_instead_of_treated_as_remainder(self):
        result = evaluate_expression("5% + 2")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"], "unsupported_expression")

    def test_declared_exponent_and_magnitude_limits_are_enforced(self):
        self.assertEqual(
            evaluate_expression("2 ** 13")["error"], "exponent_too_large")
        self.assertEqual(
            evaluate_expression("1000000000000 + 1")["error"],
            "result_out_of_range")

    def test_excessively_deep_legal_expression_returns_error(self):
        with patch("calculate._eval", side_effect=RecursionError):
            result = evaluate_expression("1 + 1")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"], "expression_too_deep")


if __name__ == "__main__":
    unittest.main()
