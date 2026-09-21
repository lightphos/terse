# Support python code for terse
### (until terse can do it)

## SQLlite

Install `uv` first, then run the setup script from this directory.

```powershell
.\install.ps1
```

For a POSIX shell:

```sh
./install.sh
```

Run the server with that same interpreter from the repository root:

```powershell
.\.venv\Scripts\python.exe support\sqliteserver.py
```

The server uses the repository-level `terse.db` file. Terse programs connect to
that file with `sqlite3://file/terse.db`; the `tcp://127.0.0.1:5000` address is
for `sqlite_rx` clients, not the native Terse database runtime.
