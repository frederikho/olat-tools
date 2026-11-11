"""Safety net for the privacy-critical anonymiser. Uses an invented workbook (fake names), never real data.
Run:  ~/.venvs/olat/bin/python -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from olat import results, session  # noqa: E402

HEADER = ["Laufnummer", "Anmeldename", "Vorname", "Nachname", "Matrikelnummer", "Homepage", "Status", "Punkte", "1_U1"]
ROW = [1, "mmuster", "Maxi", "Musterfrau", "1234567", "https://example.org/u/1", "beendet", 2.5, "My answer by Musterfrau"]


def make_workbook(path, leak_into_other_sheet=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resultate"
    ws["A1"] = "Intermediate check up"
    ws.append(HEADER)
    ws.append(ROW)
    cov = wb.create_sheet("Abdeckung Resultate")
    cov.append([None, None])
    cov.append([None, None])
    cov.append([None, None])
    cov.append([None, "Anmeldename", "Vorname", "Nachname", "Matrikelnummer", "Homepage", "Question 1"])   # header on row 4
    cov.append([None, "mmuster", "Maxi", "Musterfrau", "1234567", "https://example.org/u/1", 1.0])
    if leak_into_other_sheet:
        wb.create_sheet("Notes")["A1"] = "graded by hand: Maxi Musterfrau"
    wb.properties.creator = "Some Author"
    wb.save(path)


class AnonymizeTest(unittest.TestCase):
    def run_anonymize(self, **kw):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "results.xlsx"
        make_workbook(src, **kw)
        out, dropped, hits = results.anonymize(src, tmp / "out")
        return openpyxl.load_workbook(out), dropped, hits

    def test_identifier_columns_are_dropped_in_every_sheet(self):
        wb, dropped, hits = self.run_anonymize()
        header = [c.value for c in wb["Resultate"][2]]
        self.assertEqual(header, ["Laufnummer", "Status", "Punkte", "1_U1"])
        self.assertEqual([c.value for c in wb["Resultate"][3]][:3], [1, "beendet", 2.5])
        self.assertNotIn("Anmeldename", [c.value for c in wb["Abdeckung Resultate"][4]])
        self.assertEqual(len(dropped), 10)

    def test_clean_file_has_no_leak_hits_except_the_answer_text_naming_the_student(self):
        _, _, hits = self.run_anonymize()
        self.assertEqual(hits, ["Resultate!D3"], "a student who signs the answer with their name must be flagged")

    def test_leak_in_a_further_sheet_is_found(self):
        _, _, hits = self.run_anonymize(leak_into_other_sheet=True)
        self.assertIn("Notes!A1", hits)

    def test_author_properties_are_blank(self):
        wb, _, _ = self.run_anonymize()
        self.assertFalse(wb.properties.creator)
        self.assertFalse(wb.properties.lastModifiedBy)


class Lz4Test(unittest.TestCase):
    def test_literals_and_overlapping_match(self):
        # token 0x1? = 1 literal 'a'; then match: offset 1, length 4+4 -> 'a' repeated 9 times in total
        data = bytes([0x14, ord("a"), 0x01, 0x00])
        self.assertEqual(session.lz4_block_decompress(data, 9), b"a" * 9)


if __name__ == "__main__":
    unittest.main()
