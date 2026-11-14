
"""Automated tests for the key-value database."""

import os
import tempfile
import unittest

from main import CommandError, Database


class DatabaseTests(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "data.db")
        self.database = Database(self.path)

    def run_command(self, command):
        return self.database.execute(command)

    def test_file_and_last_write_wins(self):
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(self.run_command("SET name Malika"), "OK")
        self.run_command("SET name Ray")
        self.assertEqual(self.run_command("GET name"), "Ray")
        self.assertEqual(
            Database(self.path).execute("GET name"), "Ray"
        )

    def test_missing_delete_and_exists(self):
        self.assertEqual(self.run_command("GET missing"), "(nil)")
        self.assertEqual(self.run_command("EXISTS missing"), "0")
        self.run_command("SET a 5")
        self.assertEqual(self.run_command("DEL a"), "1")
        self.assertEqual(self.run_command("DEL a"), "0")
        self.assertEqual(
            Database(self.path).execute("EXISTS a"), "0"
        )

    def test_multi_and_range(self):
        self.run_command("MSET a 1 b 2 c 3")
        self.assertEqual(
            self.run_command("MGET a z c"),
            '["1",null,"3"]'
        )
        self.assertEqual(
            self.run_command("RANGE a b"),
            '[["a","1"],["b","2"]]'
        )

    def test_ttl_and_expiry(self):
        self.run_command("SET a value")
        self.assertEqual(self.run_command("TTL a"), "-1")
        self.assertEqual(self.run_command("EXPIRE a 10"), "1")
        self.assertGreaterEqual(
            int(self.run_command("TTL a")), 0
        )
        self.assertEqual(self.run_command("EXPIRE a 0"), "1")
        self.assertEqual(self.run_command("GET a"), "(nil)")
        self.assertEqual(
            Database(self.path).execute("GET a"), "(nil)"
        )
        self.assertEqual(self.run_command("TTL a"), "-2")

    def test_transactions(self):
        self.run_command("SET a old")
        self.run_command("BEGIN")
        self.run_command("SET a temporary")

        self.assertEqual(
            self.run_command("GET a"), "temporary"
        )
        self.assertEqual(
            Database(self.path).execute("GET a"), "old"
        )

        self.run_command("ABORT")
        self.assertEqual(self.run_command("GET a"), "old")

        self.run_command("BEGIN")
        self.run_command("SET a committed")
        self.run_command("SET b yes")
        self.run_command("COMMIT")

        restarted = Database(self.path)
        self.assertEqual(
            restarted.execute("GET a"), "committed"
        )
        self.assertEqual(
            restarted.execute("GET b"), "yes"
        )

    def test_hash_and_list(self):
        self.assertEqual(
            self.run_command("HSET profile city Dallas"), "1"
        )
        self.assertEqual(
            self.run_command("HSET profile city Austin"), "0"
        )
        self.assertEqual(
            self.run_command("HGET profile city"), "Austin"
        )
        self.assertEqual(
            self.run_command("HGETALL profile"),
            '[["city","Austin"]]'
        )

        self.assertEqual(
            self.run_command("RPUSH todo first"), "1"
        )
        self.assertEqual(
            self.run_command("LPUSH todo zero"), "2"
        )
        self.assertEqual(
            self.run_command("LRANGE todo 0 -1"),
            '["zero","first"]'
        )

        restarted = Database(self.path)
        self.assertEqual(
            restarted.execute("HGET profile city"), "Austin"
        )
        self.assertEqual(
            restarted.execute("LRANGE todo 0 -1"),
            '["zero","first"]'
        )

    def test_counters_and_flush(self):
        self.assertEqual(self.run_command("INCR count"), "1")
        self.assertEqual(self.run_command("INCR count"), "2")
        self.assertEqual(self.run_command("DECR count"), "1")
        self.assertEqual(
            Database(self.path).execute("GET count"), "1"
        )
        self.assertEqual(self.run_command("FLUSHDB"), "OK")
        self.assertEqual(
            Database(self.path).execute("EXISTS count"), "0"
        )

    def test_error_does_not_persist(self):
        self.run_command("SET count hello")

        with self.assertRaises(CommandError):
            self.run_command("INCR count")

        self.assertEqual(
            Database(self.path).execute("GET count"), "hello"
        )

    def test_quoted_values(self):
        self.run_command('SET greeting "hello world"')
        self.assertEqual(
            self.run_command("GET greeting"), "hello world"
        )


if __name__ == "__main__":
    unittest.main()
