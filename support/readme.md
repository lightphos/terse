# Support

Host helper scripts (install, tooling) until more of the toolchain lives in Terse itself.

Socket primitives (`sock.listen` / `accept` / `recv` / `send` / `close`) are provided by the C runtime so packages like `lib/cnx/http.te` can implement HTTP in pure Terse.

SQLite / host `http.serve` have been removed from the compiler; reintroduce via Terse libraries when ready.
