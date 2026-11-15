
"""Regression tests for the key-value store and Gradebot output."""

import os
import tempfile
import unittest

from main import CommandError, Database


class DatabaseTests(unittest.TestCase):
    """Exercise every required command and restart persistence."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "data.db")
        self.db = Database(self.path)

    def command(self, text):
        return self.db.execute(text)

    def test_storage_and_overwrite(self):
        self.assertTrue(os.path.isfile(self.path))
        self.assertEqual(self.command("SET name Malika"), "OK")
        self.command("SET name Ray")
        self.assertEqual(self.command("GET name"), "Ray")
        self.assertEqual(
            Database(self.path).execute("GET name"),
            "Ray"
        )

    def test_missing_and_deleted_get(self):
        self.assertEqual(self.command("GET never"), "")
        self.command("SET a value")
        self.assertEqual(self.command("EXISTS a"), "1")
        self.assertEqual(self.command("DEL a"), "1")
        self.assertEqual(self.command("GET a"), "(nil)")
        self.assertEqual(self.command("EXISTS a"), "0")

    def test_multi_and_range(self):
        self.command("MSET a 1 b 2 c 3")
        self.assertEqual(
            self.command("MGET a z c"),
            "1\n(nil)\n3"
        )
        self.assertEqual(
            self.command("RANGE b c"),
            "b\nc\nEND"
        )
        self.assertEqual(
            self.command('RANGE b ""'),
            "b\nc\nEND"
        )

    def test_expiration(self):
        self.command("SET session token")
        self.assertEqual(self.command("TTL session"), "-1")
        self.assertEqual(self.command("EXPIRE session 0"), "1")
        self.assertEqual(self.command("GET session"), "(nil)")
        self.assertEqual(self.command("TTL session"), "-2")

    def test_transactions(self):
        self.command("BEGIN")
        self.command("SET uncommitted 1")
        self.assertEqual(
            self.command("GET uncommitted"),
            "1"
        )
        self.command("ABORT")
        self.assertEqual(
            self.command("GET uncommitted"),
            "(nil)"
        )

        self.command("BEGIN")
        self.command("SET committed 2")
        self.command("COMMIT")
        self.assertEqual(
            Database(self.path).execute("GET committed"),
            "2"
        )

    def test_hash(self):
        self.assertEqual(
            self.command("HSET p name Malika"),
            "1"
        )
        self.assertEqual(
            self.command("HSET p name Ray"),
            "0"
        )
        self.assertEqual(
            self.command("HGET p name"),
            "Ray"
        )
        self.assertEqual(
            self.command("HGETALL p"),
            '[["name","Ray"]]'
        )

    def test_list_push_range_pop(self):
        self.command("RPUSH items item1")
        self.command("RPUSH items item2")
        self.command("LPUSH items item3")

        self.assertEqual(
            self.command("LRANGE items 0 -1"),
            "item3\nitem1\nitem2"
        )
        self.assertEqual(
            self.command("LPOP items"),
            "item3"
        )
        self.assertEqual(
            self.command("RPOP items"),
            "item2"
        )
        self.assertEqual(
            Database(self.path).execute("LPOP items"),
            "item1"
        )

    def test_counters_and_flush(self):
        self.assertEqual(self.command("INCR n"), "1")
        self.assertEqual(self.command("INCR n"), "2")
        self.assertEqual(self.command("DECR n"), "1")
        self.assertEqual(self.command("FLUSHDB"), "OK")
        self.assertEqual(self.command("GET n"), "(nil)")
        self.assertEqual(
            Database(self.path).execute("GET n"),
            "(nil)"
        )

    def test_atomic_failed_write(self):
        self.command("SET value words")

        with self.assertRaises(CommandError):
            self.command("INCR value")

        self.assertEqual(
            self.command("GET value"),
            "words"
        )


if __name__ == "__main__":
    unittest.main()
