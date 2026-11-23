# Terse

A compact, statically typed language that compiles to native binaries. 

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/lightphos/terse/main/install.sh | sh
export PATH="$HOME/.terse/bin:$PATH"
```

Places the host compiler in `$HOME/.terse/compiler`, libs in `$HOME/.terse/lib`, and `tc|tersec` in `$HOME/.terse/bin`.

Currently requires python and C compiler, see below.


## Quick start
```bash
# app.te

go {
  pr("This is terse!")
}
```
or
```
go pr("This is terse!")
```

### Build & Run

```bash
# build
tersec app.te
```
or
```
te app
> This is terse!
```

## Prerequisites

- Python 3.12+
- `gcc` or `clang` on `PATH`
- **OpenSSL development files** (needed for HTTPS; optional otherwise)

```
> Goal: Native compiler written in terse which produces machine code
```
### Install dependencies

On ubuntu like distros:

```bash
sudo apt
sudo apt install python3
sudo apt install gcc
sudo apt install build-essential
```
On windows:

```bash
install choco

then as admin:

choco install mingw -y
```

## Test Suite

```bash
make verify    # host unit tests
make tst       # tst/t_*.te

WIP Native compiler:
make tcc && make tcc1 && make bootstrap   # native frontend stages

C Intermediate:
python3 compiler/tersec.py build src/hi.te -o out/hi --keep-c
```

## Layout

```text
compiler/     Host compiler (tersec.py, runtime.c, tc.te)
lib/          Standard and optional packages
src/          Examples
tst/          Tests (t_*.te)
install.sh    Install tc → $HOME/.terse/
SPEC.md       Language specification
BNF.md        Grammar
benchmark/    HTTP concurrency notes
```

## Language (see SPEC)

Details live in **[SPEC.md](./SPEC.md)** and **[BNF.md](./BNF.md)**. Topics covered there:

- Keywords
- Types and primitives (`long`, `int`, `str`, lists, maps, …)
- Functions, methods, modules (`use` / `pub`)
- Control flow, pattern `if`, loops
- Records, enums, traits, generics
- Lambdas and closures
- Pipe `|>`
- Thread async `~~` / `~` and event-loop `~~>` / `~>`
- Awaitable I/O (`io.wait`, `io.recv`, `io.send`, `io.connect`)
- Arena, sockets, HTTP

## Tooling

- tersec | te -c
  - build 
- terser | te -r | te
  - run
  - test
- te [-r|-c|t] app

## Roadmap

**[roadmap.md](./roadmap.md)** 

## License

MIT
