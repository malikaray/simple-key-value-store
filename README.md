
# Simple Key-Value Store Database

## Project Description

This project is a simple persistent key-value database built
using Python.

It supports basic storage, deletion, expiration, transactions,
hash maps, lists, counters, and range queries.

## Programming Language

Python 3.12

## Features

- SET, GET, EXIT
- DEL, EXISTS
- MSET, MGET
- EXPIRE, TTL
- RANGE
- BEGIN, COMMIT, ABORT
- HSET, HGET, HGETALL
- LPUSH, RPUSH, LRANGE
- INCR, DECR
- FLUSHDB

## Database Storage

The program saves all committed changes to a file called
data.db using append-only storage.

When the database restarts, it reads the stored operations
to restore its previous data.

The in-memory index uses Python lists instead of dictionaries.

## How to Run

Open a terminal in the project directory.

Run:

    python main.py

Example:

    SET name Malika
    GET name
    SET city Dallas
    GET city
    EXIT

## Run Automated Tests

    python -m unittest discover -s tests -v

## Code Linting

Install Ruff:

    python -m pip install ruff

Check the source code:

    python -m ruff check main.py tests

## GitHub Actions

Automated tests and linting run on GitHub using
.github/workflows/ci.yml.

## Notes

- Data is stored locally in data.db.
- Commands are read from standard input.
- Results are printed to standard output.
- Transactions are committed together.
- Uncommitted transactions are discarded.
- No built-in dictionary is used for the database index.
- Multi-value results are formatted as JSON arrays.
