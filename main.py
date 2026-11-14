
"""A small persistent, append-only key-value database.

No dictionary or map is used to index keys or hash fields. The index and
hashes are represented as lists and searched linearly.
"""

import copy
import json
import os
import shlex
import sys
import time

DATABASE_FILE = "data.db"


class CommandError(Exception):
    """An invalid command or a value of an incompatible type."""


def locate(items, key):
    """Find a record by its first element, without using a dictionary."""
    for position, item in enumerate(items):
        if item[0] == key:
            return position
    return -1


def get_record(items, key, now=None):
    """Find a live record, discarding expired entries from the index."""
    position = locate(items, key)
    if position == -1:
        return None
    if now is None:
        now = time.time()
    record = items[position]
    if record[3] is not None and record[3] <= now:
        items.pop(position)
        return None
    return record


def write_record(items, key, kind, value, expires=None):
    position = locate(items, key)
    record = [key, kind, value, expires]
    if position < 0:
        items.append(record)
    else:
        items[position] = record


def require(arguments, count, usage):
    if len(arguments) != count:
        raise CommandError("usage: " + usage)


def integer(value):
    try:
        return int(value)
    except ValueError as exc:
        raise CommandError("expected an integer") from exc


def display(value):
    """Print a simple scalar or an unambiguous JSON list."""
    if value is None:
        return "(nil)"
    if isinstance(value, list):
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        )
    return str(value)


def apply(items, operation):
    """Apply one operation, returning its response."""
    action = operation[0]
    args = operation[1:]

    if action == "SET":
        key, value = args
        write_record(items, key, "string", value)
        return "OK"

    if action == "DEL":
        key = args[0]
        record = get_record(items, key)
        if record is None:
            return "0"
        items.pop(locate(items, key))
        return "1"

    if action == "MSET":
        for position in range(0, len(args), 2):
            write_record(
                items, args[position], "string", args[position + 1]
            )
        return "OK"

    if action == "EXPIRE":
        key, deadline = args
        record = get_record(items, key)
        if record is None:
            return "0"
        record[3] = deadline
        return "1"

    if action == "HSET":
        hash_name, field, value = args
        record = get_record(items, hash_name)

        if record is None:
            write_record(items, hash_name, "hash", [])
            record = get_record(items, hash_name)

        if record[1] != "hash":
            raise CommandError("wrong type: expected hash")

        position = locate(record[2], field)

        if position == -1:
            record[2].append([field, value])
            return "1"

        record[2][position][1] = value
        return "0"

    if action in ("LPUSH", "RPUSH"):
        key, value = args
        record = get_record(items, key)

        if record is None:
            write_record(items, key, "list", [])
            record = get_record(items, key)

        if record[1] != "list":
            raise CommandError("wrong type: expected list")

        if action == "LPUSH":
            record[2].insert(0, value)
        else:
            record[2].append(value)

        return str(len(record[2]))

    if action in ("INCR", "DECR"):
        key = args[0]
        record = get_record(items, key)

        if record is None:
            number = 0
        else:
            if record[1] != "string":
                raise CommandError("wrong type: expected string")
            number = integer(record[2])

        number += 1 if action == "INCR" else -1
        expires = record[3] if record is not None else None

        write_record(items, key, "string", str(number), expires)
        return str(number)

    if action == "FLUSHDB":
        items.clear()
        return "OK"

    raise CommandError("unknown write operation")


def query(items, action, args):
    """Read values without recording an event to the log."""

    if action == "GET":
        require(args, 1, "GET <key>")
        record = get_record(items, args[0])

        if record is None:
            return "(nil)"
        if record[1] != "string":
            raise CommandError("wrong type: expected string")

        return record[2]

    if action == "EXISTS":
        require(args, 1, "EXISTS <key>")
        return "1" if get_record(items, args[0]) is not None else "0"

    if action == "MGET":
        if not args:
            raise CommandError("usage: MGET <key> [key ...]")

        values = []

        for key in args:
            record = get_record(items, key)
            if record is not None and record[1] != "string":
                raise CommandError("wrong type: expected string")
            values.append(record[2] if record is not None else None)

        return display(values)

    if action == "TTL":
        require(args, 1, "TTL <key>")
        now = time.time()
        record = get_record(items, args[0], now)

        if record is None:
            return "-2"
        if record[3] is None:
            return "-1"

        return str(max(0, int(record[3] - now)))

    if action == "RANGE":
        require(args, 2, "RANGE <start> <end>")
        start, end = args
        pairs = []

        for key in sorted(item[0] for item in items):
            if start <= key <= end:
                record = get_record(items, key)
                if record is not None:
                    pairs.append([key, record[2]])

        return display(pairs)

    if action == "HGET":
        require(args, 2, "HGET <hash> <field>")
        record = get_record(items, args[0])

        if record is None:
            return "(nil)"
        if record[1] != "hash":
            raise CommandError("wrong type: expected hash")

        position = locate(record[2], args[1])
        return "(nil)" if position == -1 else record[2][position][1]

    if action == "HGETALL":
        require(args, 1, "HGETALL <hash>")
        record = get_record(items, args[0])

        if record is None:
            return "[]"
        if record[1] != "hash":
            raise CommandError("wrong type: expected hash")

        return display(sorted(record[2], key=lambda field: field[0]))

    if action == "LRANGE":
        require(args, 3, "LRANGE <key> <start> <stop>")
        start = integer(args[1])
        stop = integer(args[2])
        record = get_record(items, args[0])

        if record is None:
            return "[]"
        if record[1] != "list":
            raise CommandError("wrong type: expected list")

        values = record[2]
        size = len(values)

        if start < 0:
            start += size
        if stop < 0:
            stop += size

        start = max(0, start)
        stop = min(size - 1, stop)

        return display(values[start:stop + 1])

    raise CommandError("unknown command")


READ_COMMANDS = (
    "GET", "EXISTS", "MGET", "TTL",
    "RANGE", "HGET", "HGETALL", "LRANGE"
)

WRITE_COMMANDS = (
    "SET", "DEL", "MSET", "EXPIRE", "HSET",
    "LPUSH", "RPUSH", "INCR", "DECR", "FLUSHDB"
)


def prepare_write(action, args, now):
    """Validate a write before saving it."""

    if action == "SET":
        require(args, 2, "SET <key> <value>")

    elif action in ("DEL", "INCR", "DECR"):
        require(args, 1, action + " <key>")

    elif action == "MSET":
        if not args or len(args) % 2:
            raise CommandError(
                "usage: MSET <key> <value> [key value ...]"
            )

    elif action == "EXPIRE":
        require(args, 2, "EXPIRE <key> <seconds>")
        seconds = integer(args[1])
        args = [args[0], now + seconds]

    elif action == "HSET":
        require(args, 3, "HSET <hash> <field> <value>")

    elif action in ("LPUSH", "RPUSH"):
        require(args, 2, action + " <key> <value>")

    elif action == "FLUSHDB":
        require(args, 0, "FLUSHDB")

    else:
        raise CommandError("unknown command")

    return [action, *args]


class Database:
    """Database using a list index and an append-only file."""

    def __init__(self, path=DATABASE_FILE):
        self.path = path
        self.items = []
        self.staged = None
        self.pending = []

        # Create data.db if it does not exist.
        with open(self.path, "a", encoding="utf-8"):
            pass

        self.replay()

    def replay(self):
        """Restore saved data when the program starts."""
        with open(self.path, encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue

                try:
                    event = json.loads(line)

                    if event[0] == "TX":
                        candidate = copy.deepcopy(self.items)

                        for operation in event[1]:
                            apply(candidate, operation)

                        self.items = candidate

                    else:
                        apply(self.items, event)

                except (
                    ValueError, TypeError, IndexError, CommandError
                ) as exc:
                    raise RuntimeError(
                        "Invalid database log"
                    ) from exc

    def append(self, event):
        """Append and flush every committed write."""
        with open(
            self.path, "a", encoding="utf-8"
        ) as destination:
            destination.write(
                json.dumps(event, ensure_ascii=False) + "\n"
            )
            destination.flush()
            os.fsync(destination.fileno())

    def execute(self, line):
        """Process one input command."""
        try:
            parts = shlex.split(line, posix=True)
        except ValueError:
            return "ERROR: unmatched quotation mark"

        if not parts:
            return None

        action = parts[0].upper()
        args = parts[1:]

        if action == "EXIT":
            require(args, 0, "EXIT")
            return "__EXIT__"

        if action == "BEGIN":
            require(args, 0, "BEGIN")

            if self.staged is not None:
                raise CommandError("transaction already active")

            self.staged = copy.deepcopy(self.items)
            self.pending = []
            return "OK"

        if action == "ABORT":
            require(args, 0, "ABORT")

            if self.staged is None:
                raise CommandError("no active transaction")

            self.staged = None
            self.pending = []
            return "OK"

        if action == "COMMIT":
            require(args, 0, "COMMIT")

            if self.staged is None:
                raise CommandError("no active transaction")

            if self.pending:
                self.append(["TX", self.pending])

            self.items = self.staged
            self.staged = None
            self.pending = []
            return "OK"

        state = (
            self.staged
            if self.staged is not None
            else self.items
        )

        if action in READ_COMMANDS:
            return query(state, action, args)

        if action not in WRITE_COMMANDS:
            raise CommandError("unknown command: " + action)

        operation = prepare_write(action, args, time.time())

        # Validate the operation before writing to disk.
        candidate = copy.deepcopy(state)
        result = apply(candidate, operation)

        if self.staged is not None:
            self.staged = candidate
            self.pending.append(operation)
        else:
            self.append(operation)
            self.items = candidate

        return result


def main():
    try:
        database = Database()
    except (OSError, RuntimeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1

    # Read commands from standard input (STDIN).
    for line in sys.stdin:
        try:
            result = database.execute(line)

            if result == "__EXIT__":
                break

            if result is not None:
                print(result, flush=True)

        except CommandError as exc:
            print("ERROR: " + str(exc), flush=True)

        except OSError as exc:
            print(
                "ERROR: storage failure: " + str(exc),
                flush=True
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
