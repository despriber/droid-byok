import unittest

from droid_byok.tui import live_model_rows, model_id_from_row_key


class LiveModelRowsTests(unittest.TestCase):
    def test_duplicate_model_ids_get_unique_table_keys(self) -> None:
        settings = {
            "customModels": [
                {"id": "custom:shared", "model": "first"},
                {"id": "custom:shared", "model": "second"},
            ],
            "sessionDefaultSettings": {"model": "custom:shared"},
        }

        rows = live_model_rows(settings)

        self.assertEqual([row[-1] for row in rows], ["0:custom:shared", "1:custom:shared"])
        self.assertEqual(len({row[-1] for row in rows}), 2)
        self.assertEqual(model_id_from_row_key(rows[0][-1]), "custom:shared")

    def test_legacy_row_key_is_still_a_model_id(self) -> None:
        self.assertEqual(model_id_from_row_key("custom:model"), "custom:model")


if __name__ == "__main__":
    unittest.main()
