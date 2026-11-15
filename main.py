
"""Append-only persistent key-value store with a linear-list index.

Commands use STDIN/STDOUT, with no prompts or startup banners.
"""

import copy
import json
import os
import shlex
import sys
import time

DATABASE_FILE = "data.db"


class CommandError(Exception):
    """Error returned for invalid commands or incompatible values."""


def index_of(items, key):
    """Locate a key without using Python dictionaries."""
    for i, item in enumerate(items):
        if item[0] == key:
            return i
    return -1


def live_record(items, key, now=None):
    """Find a live record, lazily expiring outdated records."""
    i = index_of(items, key)
    if i == -1:
        return None

    record = items[i]

    if now is None:
        now = time.time()

    if record[3] is not None and record[3] <= now:
        items.pop(i)
        return None

    return record


def replace_record(items, key, kind, value, expiry=None):
    """Replace a key in the linear index (last write wins)."""
    record = [key, kind, value, expiry]
    i = index_of(items, key)

    if i == -1:
        items.append(record)
    else:
        items[i] = record


def check_count(args, size, help_text):
    """Enforce command arity."""
    if len(args) != size:
        raise CommandError("usage: " + help_text)


def parse_int(value):
    """Parse a signed integer."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError("expected integer") from exc


def remember(seen, key):
    """Record keys written at least once, including after deletion."""
    if key not in seen:
        seen.append(key)


def apply(items, seen, operation):
    """Apply a validated persistent operation to a working snapshot."""
    cmd, *args = operation

    if cmd == "SET":
        key, value = args
        replace_record(items, key, "string", value)
        remember(seen, key)
        return "OK"

    if cmd == "MSET":
        for i in range(0, len(args), 2):
            replace_record(items, args[i], "string", args[i + 1])
            remember(seen, args[i])

        return "OK"

    if cmd == "DEL":
        key = args[0]
        record = live_record(items, key)

        if record is None:
            return "0"

        items.pop(index_of(items, key))
        return "1"

    if cmd == "EXPIRE":
        key, expiry = args
        record = live_record(items, key)

        if record is None:
            return "0"

        record[3] = expiry
        return "1"

    if cmd == "HSET":
        key, field, value = args
        record = live_record(items, key)

        if record is None:
            replace_record(items, key, "hash", [])
            remember(seen, key)
            record = live_record(items, key)

        if record[1] != "hash":
            raise CommandError("wrong type")

        i = index_of(record[2], field)

        if i < 0:
            record[2].append([field, value])
            return "1"

        record[2][i][1] = value
        return "0"

    if cmd in ("LPUSH", "RPUSH"):
        key, value = args
        record = live_record(items, key)

        if record is None:
            replace_record(items, key, "list", [])
            remember(seen, key)
            record = live_record(items, key)

        if record[1] != "list":
            raise CommandError("wrong type")

        if cmd == "LPUSH":
            record[2].insert(0, value)
        else:
            record[2].append(value)

        return str(len(record[2]))

    if cmd in ("LPOP", "RPOP"):
        key = args[0]
        record = live_record(items, key)

        if record is None:
            return "(nil)"

        if record[1] != "list":
            raise CommandError("wrong type")

        if not record[2]:
            return "(nil)"

        if cmd == "LPOP":
            return record[2].pop(0)

        return record[2].pop()

    if cmd in ("INCR", "DECR"):
        key = args[0]
        record = live_record(items, key)

        if record is None:
            value, expiry = 0, None
        else:
            if record[1] != "string":
                raise CommandError("wrong type")

            value = parse_int(record[2])
            expiry = record[3]

        value += 1 if cmd == "INCR" else -1

        replace_record(items, key, "string", str(value), expiry)
        remember(seen, key)

        return str(value)

    if cmd == "FLUSHDB":
        items.clear()
        return "OK"

    raise CommandError("unknown write operation")


def read(items, seen, cmd, args):
    """Evaluate a read without creating an append-only log entry."""

    if cmd == "GET":
        check_count(args, 1, "GET key")
        record = live_record(items, args[0])

        if record is None:
            # Differentiate never-created and previously deleted keys.
            return "(nil)" if args[0] in seen else ""

        if record[1] != "string":
            raise CommandError("wrong type")

        return record[2]

    if cmd == "EXISTS":
        check_count(args, 1, "EXISTS key")

        return "1" if live_record(items, args[0]) else "0"

    if cmd == "MGET":
        if not args:
            raise CommandError("usage: MGET key [key ...]")

        values = []

        for key in args:
            record = live_record(items, key)

            if record is not None and record[1] != "string":
                raise CommandError("wrong type")

            if record is None:
                values.append("(nil)")
            else:
                values.append(record[2])

        return "\n".join(values)

    if cmd == "TTL":
        check_count(args, 1, "TTL key")

        now = time.time()
        record = live_record(items, args[0], now)

        if record is None:
            return "-2"

        if record[3] is None:
            return "-1"

        return str(max(0, int(record[3] - now)))

    if cmd == "RANGE":
        check_count(args, 2, "RANGE start end")

        start, end = args
        keys = []

        for key in sorted(record[0] for record in items):
            if (not start or key >= start) and (
                not end or key <= end
            ) and live_record(items, key) is not None:
                keys.append(key)

        return "\n".join(keys + ["END"])

    if cmd == "HGET":
        check_count(args, 2, "HGET hash field")

        record = live_record(items, args[0])

        if record is None:
            return "(nil)"

        if record[1] != "hash":
            raise CommandError("wrong type")

        i = index_of(record[2], args[1])

        if i == -1:
            return "(nil)"

        return record[2][i][1]

    if cmd == "HGETALL":
        check_count(args, 1, "HGETALL hash")

        record = live_record(items, args[0])

        if record is None:
            return "[]"

        if record[1] != "hash":
            raise CommandError("wrong type")

        return json.dumps(
            sorted(record[2]),
            separators=(",", ":")
        )

    if cmd == "LRANGE":
        check_count(args, 3, "LRANGE key start stop")

        start = parse_int(args[1])
        stop = parse_int(args[2])

        record = live_record(items, args[0])

        if record is None:
            return ""

        if record[1] != "list":
            raise CommandError("wrong type")

        values = record[2]
        n = len(values)

        if start < 0:
            start += n

        if stop < 0:
            stop += n

        start = max(start, 0)
        stop = min(stop, n - 1)

        return "\n".join(values[start:stop + 1])

    raise CommandError("unknown read operation")


READS = (
    "GET",
    "EXISTS",
    "MGET",
    "TTL",
    "RANGE",
    "HGET",
    "HGETALL",
    "LRANGE",
)

WRITES = (
    "SET",
    "MSET",
    "DEL",
    "EXPIRE",
    "HSET",
    "LPUSH",
    "RPUSH",
    "LPOP",
    "RPOP",
    "INCR",
    "DECR",
    "FLUSHDB",
)


def prepare(cmd, args):
    """Validate write command arguments and freeze relative TTLs."""

    if cmd == "SET":
        check_count(args, 2, "SET key value")

    elif cmd == "MSET":
        if not args or len(args) % 2:
            raise CommandError(
                "usage: MSET key value [key value ...]"
            )

    elif cmd in ("DEL", "INCR", "DECR", "LPOP", "RPOP"):
        check_count(args, 1, cmd + " key")

    elif cmd == "EXPIRE":
        check_count(args, 2, "EXPIRE key seconds")

        args = [
            args[0],
            time.time() + parse_int(args[1])
        ]

    elif cmd == "HSET":
        check_count(args, 3, "HSET hash field value")

    elif cmd in ("LPUSH", "RPUSH"):
        check_count(args, 2, cmd + " key value")

    elif cmd == "FLUSHDB":
        check_count(args, 0, "FLUSHDB")

    else:
        raise CommandError("unknown command")

    return [cmd, *args]


class Database:
    """Persistent database using list indexing and append-only storage."""

    def __init__(self, path=DATABASE_FILE):
        self.path = path
        self.items = []
        self.seen = []
        self.transaction = None
        self.pending = []

        with open(self.path, "a", encoding="utf-8"):
            pass

        self.replay()

    def replay(self):
        """Recover database state by replaying committed log entries."""

        with open(self.path, encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue

                event = json.loads(line)

                if event[0] == "TX":
                    for operation in event[1]:
                        apply(
                            self.items,
                            self.seen,
                            operation
                        )
                else:
                    apply(
                        self.items,
                        self.seen,
                        event
                    )

    def append(self, event):
        """Append and flush every committed write to disk."""

        with open(
            self.path,
            "a",
            encoding="utf-8"
        ) as out:
            out.write(
                json.dumps(
                    event,
                    ensure_ascii=False
                ) + "\n"
            )

            out.flush()
            os.fsync(out.fileno())

    def execute(self, text):
        """Execute one CLI command and persist committed operations."""

        try:
            parts = shlex.split(text)
        except ValueError as exc:
            raise CommandError("invalid quotes") from exc

        if not parts:
            return None

        cmd, *args = parts
        cmd = cmd.upper()

        if cmd == "EXIT":
            check_count(args, 0, "EXIT")
            return "__EXIT__"

        if cmd == "BEGIN":
            check_count(args, 0, "BEGIN")

            if self.transaction is not None:
                raise CommandError(
                    "transaction already active"
                )

            self.transaction = [
                copy.deepcopy(self.items),
                self.seen[:]
            ]

            self.pending = []
            return "OK"

        if cmd == "ABORT":
            check_count(args, 0, "ABORT")

            if self.transaction is None:
                raise CommandError("no transaction")

            # Remember keys created in aborted transactions.
            for operation in self.pending:
                if operation[0] == "MSET":
                    for i in range(
                        1, len(operation), 2
                    ):
                        remember(
                            self.seen,
                            operation[i]
                        )

                elif operation[0] in (
                    "SET",
                    "HSET",
                    "LPUSH",
                    "RPUSH",
                    "INCR",
                    "DECR",
                ):
                    remember(
                        self.seen,
                        operation[1]
                    )

            self.transaction = None
            self.pending = []

            return "OK"

        if cmd == "COMMIT":
            check_count(args, 0, "COMMIT")

            if self.transaction is None:
                raise CommandError("no transaction")

            if self.pending:
                self.append([
                    "TX",
                    self.pending
                ])

            self.items, self.seen = self.transaction

            self.transaction = None
            self.pending = []

            return "OK"

        if self.transaction is None:
            items = self.items
            seen = self.seen
        else:
            items, seen = self.transaction

        if cmd in READS:
            return read(items, seen, cmd, args)

        if cmd not in WRITES:
            raise CommandError(
                "unknown command: " + cmd
            )

        operation = prepare(cmd, args)

        new_items = copy.deepcopy(items)
        new_seen = seen[:]

        response = apply(
            new_items,
            new_seen,
            operation
        )

        if self.transaction is not None:
            self.transaction = [
                new_items,
                new_seen
            ]

            self.pending.append(operation)

        else:
            self.append(operation)

            self.items = new_items
            self.seen = new_seen

        return response


def main():
    """Process commands from STDIN and send results to STDOUT."""

    try:
        database = Database()

    except (
        OSError,
        ValueError,
        TypeError,
        IndexError
    ) as exc:
        print(
            "ERROR: database recovery failed: " + str(exc),
            file=sys.stderr
        )
        return 1

    for line in sys.stdin:
        try:
            result = database.execute(line)

            if result == "__EXIT__":
                break

            if result is not None:
                print(
                    result,
                    flush=True
                )

        except (
            CommandError,
            OSError
        ) as exc:
            print(
                "ERROR: " + str(exc),
                flush=True
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
