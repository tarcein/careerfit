import unittest

import db
from scripts.migrate_sqlite_to_supabase import _postgres_value


class PostgresCompatibilityTests(unittest.TestCase):
    def test_translates_sqlite_placeholders_and_ignore(self):
        translated = db._postgres_sql(
            "INSERT OR IGNORE INTO embeddings(user_id, model) VALUES (?, ?)"
        )
        self.assertEqual(
            translated,
            "INSERT INTO embeddings(user_id, model) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        )

    def test_translates_sqlite_aggregates(self):
        translated = db._postgres_sql(
            "SELECT json_extract(v.profile_json, '$.confidence'), "
            "GROUP_CONCAT(DISTINCT js.skill_type)"
        )
        self.assertIn("v.profile_json::jsonb ->> 'confidence'", translated)
        self.assertIn("double precision", translated)
        self.assertIn("STRING_AGG(DISTINCT js.skill_type, ',')", translated)
        self.assertIn(
            "ROUND(AVG(js.importance)::numeric, 2)::double precision",
            db._postgres_sql("SELECT ROUND(AVG(js.importance), 2)"),
        )
        grouped = db._postgres_sql(
            "SELECT js.skill_name, GROUP_CONCAT(DISTINCT js.skill_type) "
            "ORDER BY average_importance DESC, js.skill_name"
        )
        self.assertIn("MIN(js.skill_name) AS skill_name", grouped)
        self.assertIn("average_importance DESC, skill_name", grouped)

    def test_postgres_row_supports_name_and_position(self):
        row = db._PostgresRow(id=7, name="profile")
        self.assertEqual(row["id"], 7)
        self.assertEqual(row[0], 7)

    def test_migration_removes_postgres_invalid_nul(self):
        self.assertEqual(_postgres_value("PDF\x00text"), "PDFtext")
        self.assertEqual(_postgres_value(3), 3)


if __name__ == "__main__":
    unittest.main()
