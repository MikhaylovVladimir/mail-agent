import unittest
from benchmark_cases import mail_cases,VOICE_PHRASES
from functional_benchmark import distance,normalized


class BenchmarkTests(unittest.TestCase):
    def test_operations_and_boundary_corpora(self):
        import tempfile
        from pathlib import Path
        from functional_benchmark import operation_tests,boundary_tests
        with tempfile.TemporaryDirectory() as folder:
            for operation in (operation_tests,boundary_tests):
                report=operation(Path(folder))
                self.assertEqual(report['total'],30)
                self.assertEqual(report['passed'],30)
    def test_fixed_corpus_unique_cases_and_balanced_categories(self):
        cases=mail_cases()
        self.assertEqual(len(cases),90)
        self.assertEqual(len({row[0] for row in cases}),90)
        self.assertEqual(len({row[3] for row in cases}),90)
        for category in {row[1] for row in cases}:
            self.assertEqual(sum(row[1]==category for row in cases),10)

    def test_wer_is_edit_distance_not_similarity_ratio(self):
        self.assertEqual(distance('a b c'.split(),'a x c'.split()),1)
        self.assertEqual(distance(['a'],['a','b']),1)
        self.assertEqual(distance(['a','b'],['a']),1)
        self.assertEqual(normalized('Отчёт, ГОТОВ!'),'отчет готов')
        self.assertEqual(len(VOICE_PHRASES),30)
