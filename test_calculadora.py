import unittest
from calculadora import soma, subtrai, multiplica, divide


class TestCalculadora(unittest.TestCase):
    def test_soma(self):
        self.assertEqual(soma(2, 3), 5)
        self.assertEqual(soma(-1, 1), 0)
        self.assertEqual(soma(0, 0), 0)
        self.assertEqual(soma(1.5, 2.5), 4.0)

    def test_subtrai(self):
        self.assertEqual(subtrai(5, 3), 2)
        self.assertEqual(subtrai(0, 5), -5)
        self.assertEqual(subtrai(-2, -3), 1)
        self.assertEqual(subtrai(3.5, 1.2), 2.3)

    def test_multiplica(self):
        self.assertEqual(multiplica(3, 4), 12)
        self.assertEqual(multiplica(-2, 3), -6)
        self.assertEqual(multiplica(0, 100), 0)
        self.assertEqual(multiplica(1.5, 2), 3.0)

    def test_divide(self):
        self.assertEqual(divide(10, 2), 5)
        self.assertEqual(divide(7, 2), 3.5)
        self.assertEqual(divide(-6, 3), -2)
        self.assertEqual(divide(0, 5), 0)

    def test_divide_por_zero(self):
        with self.assertRaises(ValueError) as context:
            divide(10, 0)
        self.assertEqual(str(context.exception), "Não é possível dividir por zero")


if __name__ == "__main__":
    unittest.main()