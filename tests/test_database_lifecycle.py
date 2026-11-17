"""Keep real SQLite handles alive to detect leaks even on POSIX filesystems."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_generator import ROOT
from test_master_import import write_fixture
import test_joint_packages as joint_packages
import test_repeated_records as repeated_records
import database
import import_excel


class DatabaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "classes.db"
        self.connections = []
        self.factory = sqlite3.Connection
        real_connect = sqlite3.connect

        def connect(*args, **kwargs):
            kwargs.setdefault("factory", self.factory)
            connection = real_connect(*args, **kwargs)
            # Strong references prevent GC from hiding a missing close().
            self.connections.append(connection)
            return connection

        self.addCleanup(self.close_connections)
        self.enterContext(patch("sqlite3.connect", side_effect=connect))
        self.enterContext(patch.object(database, "DB_PATH", self.db))

    def close_connections(self):
        # If a regression assertion fails, release the test-owned handles before
        # removing its temporary directory. This never suppresses cleanup errors.
        for connection in self.connections:
            connection.close()

    def assert_closed(self, connections):
        self.assertTrue(connections, "The exercised operation opened no SQLite connections")
        for connection in connections:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                connection.execute("SELECT 1")

    def test_route_and_migration_tests_do_not_rely_on_garbage_collection(self):
        cases = (
            (joint_packages.JointPackageRouteTests, "test_classes_api_exposes_actual_member_ids_and_full_joint_metadata"),
            (joint_packages.JointPackageRouteTests, "test_faculty_scope_does_not_output_joint_members_in_other_faculties"),
            (joint_packages.JointPackageRouteTests, "test_two_joint_members_have_two_packages_and_six_joint_docs"),
            (joint_packages.JointPackageRouteTests, "test_unselected_joint_member_rule_conflict_blocks_generation"),
            (repeated_records.RepeatedRecordsTests, "test_child_migration_is_idempotent_and_preserves_existing_records"),
            (repeated_records.RepeatedRecordsTests, "test_joint_edges_across_rows_unique_packages_and_frontend_choices"),
            (repeated_records.RepeatedRecordsTests, "test_legacy_scalar_contacts_and_prerequisites_backfilled"),
        )
        for case_type, method in cases:
            with self.subTest(case=method):
                start = len(self.connections)
                result = unittest.TestResult()
                case_type(method).run(result)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                self.assert_closed(self.connections[start:])

    def test_database_readers_close_successful_queries(self):
        database.init_db(self.db, seed=False)
        for reader in (database.get_faculties, database.get_programmes, database.get_classes,
                       database.get_classes_full, database.get_academic_years):
            with self.subTest(reader=reader.__name__):
                start = len(self.connections)
                reader()
                self.assert_closed(self.connections[start:])

    def test_database_readers_close_failed_queries(self):
        # A database without tables makes each real query fail, while retaining
        # the connections proves they are closed without waiting for collection.
        for reader in (database.get_faculties, database.get_programmes, database.get_classes,
                       database.get_classes_full, database.get_academic_years):
            with self.subTest(reader=reader.__name__):
                start = len(self.connections)
                with self.assertRaises(sqlite3.OperationalError):
                    reader()
                self.assert_closed(self.connections[start:])

    def test_connection_setup_failure_closes_unreturned_handle(self):
        class FailedForeignKeys(sqlite3.Connection):
            def execute(self, statement, *args, **kwargs):
                if statement == "PRAGMA foreign_keys = ON":
                    raise sqlite3.OperationalError("foreign-key setup failed")
                return super().execute(statement, *args, **kwargs)

        self.factory = FailedForeignKeys
        with self.assertRaisesRegex(sqlite3.OperationalError, "foreign-key setup failed"):
            database.get_connection()
        self.assert_closed(self.connections)

    def test_migration_failure_closes_connection_and_preserves_error(self):
        error = database.RuleMigrationRequiredError("Review required")
        with patch.object(database, "_migrate_schema", side_effect=error):
            with self.assertRaises(database.RuleMigrationRequiredError) as caught:
                database.init_db(self.db, seed=False)
        self.assertIs(error, caught.exception)
        self.assert_closed(self.connections)

    def test_failed_import_schema_closes_staging_and_preserves_existing_database(self):
        workbook = self.root / "master.xlsx"
        write_fixture(workbook)
        import_excel.import_data(workbook, self.db)
        original = self.db.read_bytes()
        schema = self.root / "broken.sql"
        schema.write_text("this is invalid SQL", encoding="utf-8")
        with patch.object(import_excel, "SCHEMA_PATH", schema):
            with self.assertRaisesRegex(sqlite3.OperationalError, "syntax error"):
                import_excel.import_data(workbook, self.db)
        self.assertEqual(original, self.db.read_bytes())
        self.assertEqual([], list(self.root.glob(".classes-*.db")))
        self.assert_closed(self.connections)


if __name__ == "__main__":
    unittest.main()
