# Terse

Compact, statically typed language that compiles to native binaries via a C backend.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/lightphos/terse/main/install.sh | sh
export PATH="$HOME/.terse/bin:$PATH"
```

Places the host compiler in `~/.terse/compiler`, libs in `~/.terse/lib`, and `tc` in `~/.terse/bin`.

```bash
tc build app.te -o ~/.terse/out/app
~/.terse/out/app
# or
tc run app.te
```

From a local clone: `sh install.sh`. Overrides: `TERSE_HOME`, `TERSE_REPO`, `TERSE_REF`.

## Prerequisites

- Python 3.12+
- `gcc` or `clang` on `PATH`
- **OpenSSL development files** (needed for HTTPS; optional otherwise)

The compiler **probes** for OpenSSL and passes `-I`/`-L` automatically (Homebrew, MSYS2, system paths, `pkg-config`). If none is found, it builds with `-DTERSE_NO_TLS` (no HTTPS).

| Platform | Install OpenSSL |
|----------|-----------------|
| macOS | `brew install openssl` |
| Debian/Ubuntu/WSL | `sudo apt install libssl-dev` |
| Fedora | `sudo dnf install openssl-devel` |
| Windows (MSYS2) | `pacman -S mingw-w64-ucrt-x86_64-openssl` |
| Windows (choco) | `choco install openssl` |

```bash
# force no TLS
export TERSE_NO_TLS=1

# or point at a custom OpenSSL
export OPENSSL_ROOT_DIR=/path/to/openssl
```

## From a clone

```bash
python3 compiler/tersec.py build src/hi.te -o ~/.terse/out/hi
~/.terse/out/hi

make run.hi
make verify    # host unit tests
make tst       # tst/t_*.te
make tcc && make tcc1 && make bootstrap   # native frontend stages
```

## Layout

```text
compiler/     Host compiler (tersec.py, runtime.c, tc.te)
lib/          Standard and optional packages
src/          Examples
tst/          Tests (t_*.te)
install.sh    Install tc → ~/.terse/
SPEC.md       Language specification
BNF.md        Grammar
benchmark/    HTTP concurrency notes
```

## Language (see SPEC)

Details live in **[SPEC.md](./SPEC.md)** and **[BNF.md](./BNF.md)**. Topics covered there:

- Types and primitives (`long`, `int`, `str`, lists, maps, …)
- Functions, methods, modules (`use` / `pub`)
- Control flow, pattern `if`, loops
- Records, enums, traits, generics
- Lambdas and closures
- Pipe `|>`
- Thread async `~~` / `~` and event-loop `~~>` / `~>`
- Awaitable I/O (`io.wait`, `io.recv`, `io.send`, `io.connect`)
- Arena, sockets, HTTP (`lib/cnx`)
- Compiler pipeline and status

Examples: `src/` · tests: `tst/` · async demo: `src/loop_wait.te` · I/O: `src/io_await.te`.

## Benchmarks

See **[benchmark/BENCH.md](./benchmark/BENCH.md)** (blocking `http.srv` vs non-blocking `nhttp.asrv`).

## Roadmap

**[roadmap.md](./roadmap.md)** — next work and native-lift plan (if present in tree).

## License

MIT
