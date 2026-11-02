# Terse Roadmap

Living plan for the next work items.  
**Reference compiler:** `tersec.py` (host) · **Grammar/spec:** `TERSE_BNF.md`, `SPEC.md` (0.3) · **Native:** `tc.te` (subset)

Status legend: **Done** · **Next** · **Later** · **Parked**

---

## 0. Current baseline (Done)

The repo is at a meaningful working baseline: the host compiler is active, the unit and Terse test suite are green, and the near-term work is mostly semantic clarity and documentation discipline rather than missing tooling fundamentals.

- Host compile to C (`gcc`/`clang -O0 -std=c11`)
- Core syntax: `val`/`var`/`fix`, `fn`, `go`, `if`/`else`, ternary `? :`, `lp` (C-style + for-in), `brk`/`skip`
- Types: `long`, `int`, `short`, `char`, `byte`, `flt`, `dbl`, `bool`, `str`
- Width-accurate lists: `[int]`, `[dbl]`, `[str]`, … + concat/push/`len`
- Records (`rec`), enums (`en`, public by default), traits (`tr`, limited)
- Pattern-based `if` arms, modules (`use`/`pub`), parallel `tst/` ↔ `src/`
- `std.str`, `std.io`, `std.tst` (`eq` / `ne`)
- Hard diagnostics: unknown name/function, type mismatch (abort before gcc)
- Bootstrap path for `tc.te` (stage0 → stage1)
- Docs: `SPEC.md`, `TERSE_BNF.md`, compiler tests in `compiler/test_compiler.py`

### Review notes folded into the roadmap

These are the main non-trivial issues still worth tracking:

- Container value semantics: document whether list/map values are copied, shared, or otherwise alias-safe.
- `env()` contract: specify process scope, persistence behavior, setter return semantics, and error handling.
- Trait dispatch model: clarify whether dispatch is monomorphized, vtable-based, or adapter-based.
- Generic pattern names: decide the stable naming strategy for generated constructor and pattern-arm identifiers.
- Lambda capture semantics: document supported captures and restrictions for nested functions.
- Error recovery: improve diagnostics beyond the current fail-fast abort model.
- Backend abstraction: decide whether a C-only pipeline remains acceptable or whether an internal IR is worth introducing.
- Documentation hygiene: keep README, AGENTS, roadmap, and the language spec aligned on the canonical file names and status.

These issues are not blockers for the current working baseline, but they are the highest-value semantic and docs work for the next stabilization pass.

---

## 1. Next (usable language polish)

Priority order for the **host** — keep `make verify` / tests green.  
Each item notes when **`tc.te` should be updated** (if at all).


### 1.0 Output directory & library cache  **Done (host)**
- Default binaries: `~/.terse/out/<name>` (override with absolute `-o` or `TERSE_OUT`)
- Shared runtime object: `~/.terse/out/lib/terse_rt.o` (built once)
- Library objects: `tersec.py lib module.te` → `~/.terse/out/lib/<name>.o` (+ `.meta` mtimes)
- Incremental: skip rebuild when binary newer than sources (`-f` / `--force` to rebuild)
- App build links `lib/*.o` when present; use `--no-libs` to disable
- Env: `TERSE_HOME` (default `~/.terse`), `TERSE_OUT`, `TERSE_LIB`, `CC`

**`tc.te`:** lift default out path + argv later (T1); lib linker after host stable (new T9)

### 1.1 Environment API  **Done (host)**
```terse
env("KEY") = "value"   // set → env_set
ret env("KEY")         // get → getenv; missing → ""
```
- Tests: `src/env.te`, `tst/t_env.te`
- **`tc.te`:** T2 done — `terse_env` / `terse_env_set` + emit for `env(k)=v`

### 1.2 Richer type diagnostics  **Done (host)**
- `ret` vs declared return type
- Function body yield vs return type
- Annotated `val`/`var` vs value
- Assignment / list concat-push / mixed list elements
- Clearer `use` module-not-found (search paths + hint)

- Return-type vs `ret` value mismatches (with line:col when available)
- List element type mismatches (`[int]` vs `[dbl]`)
- Clear messages for bad `use` paths / missing modules
- Prefer hard errors over silent `long` defaults where practical
- **`tc.te`:** **do not** mirror full diagnostics yet; host remains the conformance checker. Revisit only if native is used as the daily compiler and opaque C failures dominate

### 1.3 Freeze std surface  **Done (host)**
Locked in `SPEC.md` §8 — only these are the supported host surface:

| Module / kind | Surface |
|---------------|---------|
| `std.str` | SPEC §8 string API; `rpl` and `rpt` implemented in `lib/std/str.te` |
| `std.io`  | `in`, `out` |
| `std.tst` | `eq`, `ne`, `chk`, `report` |
| Maps      | `m[k]`, `m[k]=v`, `has(m,k)`, `keys(m)`, `len(m)`, `lp k:m` |
| Env       | `env(k)`, `env(k)=v` |
| Core      | `pr`, `len`, `arg` |

No silent expansion of std without a SPEC/BNF note.

- **`tc.te`:** when lifting std, only emit calls the native runtime already has

### 1.4b Optional packages (`lib/`)  **Done (host)**
- SPEC §5 + README: `lib/<name>.te` → `use name` (e.g. `math`, `http` stub)
- Tests: `tst/t_math.te`, `tst/t_http.te`
- No package registry

### 1.4 List / map edge cases  **Done (host, core)** / polish **Later**
- Empty typed lists `var xs: [int] = []`, width lists, push/concat/`len` — working
- Tests cover `map`, all primitive list element types, and rejected mixed list types
- Maps `{str:long}`: `{:}`, put/get, `has`, `keys`, `len`, `lp k:m` — tests `t_map_has`, `t_map_lp`
- Bounds process-exit with `index`/`len` in message; tests cover negative and upper-bound indexes **Done (host)**
- **`tc.te`:** T3/T4 when native must compile non-`long` lists / maps

### 1.5 Tooling quality gate  **Next**
- `make verify` = `test_compiler.py` + selected `tst/*.te`
- `test.sh` continues to list failed files
- Keep unknown-name / mismatch tests in the suite
- **`tc.te`:** optional later — a `make bootstrap-verify` that rebuilds stage0→stage1 and compiles a small smoke set with the native binary

---

## 2. Near-term language (after §1)

### 2.0 Generics phase 1–2  **Done (host)**
- `fn f[T](...)` + monomorphize; infer or `f[long](...)`
- `rec Box[T]`, `en Opt[T]` + monomorphize (`Box[long] {…}`, `Opt[long].Some(…)`)
- Examples: `src/generic_demo.te`, `src/generic_rec_en.te`
- T1 parametric `tr Eq[T]` parse + structural sat after subst **Done**
- Later: `T: Eq` bounds (T2), pattern-arm sugar without `Opt__long`



### 2.1 String `+` and minimal `fmt`  **Done (host)**
- Official concat: `"a" + x` (`str` with `str` / `long` / `bool`)
- Minimal helper: `fmt(a, b, ...)` → stringify + concat (no `{x}` interpolation)
- Examples: `src/hello.te`, `src/fmt_demo.te`, `src/quickstart.te`
- **`tc.te`:** optional later — emit as nested `str_concat` / `str_from_*`

### 2.2 Better errors for C backend failures  **Later**
- Surface first gcc/clang error line mapped to terse source when possible
- Reduce “C compile failed” without context
- **`tc.te`:** low priority; native already prints `TC_GCC_ERROR`. Improve only if users compile primarily with `tc`

### 2.3 Public API defaults review  **Done (host)**
- Confirmed: `en` public; `fn`/`rec`/`tr`/`fix` private unless `pub` (`pub fix` to export)
- SPEC §4 quick reference + tests may call non-pub from parallel `src/`
- Example CLI story: `src/cli_story.te` (`arg` / `env` / `fmt`)
- **`tc.te`:** update module export filtering when native gains real `use`/`pub` (see §3.3)

### 2.4 `use` / package paths  **Later**
- Document search order (same dir → parallel `src/` → project `src/` → root)
- Optional: simple `std.` always resolves without path games
- **`tc.te`:** large lift — implement only when native must compile multi-file programs. Prefer host for modules until then

---

## 3. Native compiler (`tc.te`) — when to update

**Goal:** useful stage compiler, **not** full host parity.

### 3.1 Standing rules

1. **Host first.** Land the feature in `tersec.py` + tests + SPEC/`terse_bnf` before teaching `tc.te`.
2. **Update `tc.te` only when one of these is true:**
   - Bootstrap **breaks** or cannot express a construct it needs to compile itself
   - A **demo / smoke program** is meant to be compiled by native and fails
   - Native is the **daily** compiler for a workflow and a gap blocks real use
   - A host feature is **stable ≥1 verify cycle** and is on the lift list below
3. **Do not** chase host parity feature-by-feature for its own sake.
4. After any `tc.te` change: `python3 tersec.py build tc.te -o out/tc-stage0` → run stage0 on `tc.te` → smoke-compile a tiny `.te`.

### 3.2 Status table

| Item | Status | Update `tc.te` when… |
|------|--------|----------------------|
| Bootstrap stage0→stage1 (Linux/macOS, `-O0`) | **Done** | Regression only |
| CLI: argv source + optional output; default `~/.terse/out/<stem>` | **Done** | — |
| `env` get/set | **Host + native Done** | — |
| Width-accurate lists / maps | After host §1.4 stable | Native must compile non-`long` list programs |
| Numeric types beyond `long` | Later | Same as lists — when demos need `int`/`dbl` in native path |
| Modules `use` / `pub` | Later | Multi-file native compiles are required |
| Enums + pattern `if` | Later | Bootstrap or demos need `en` under native |
| Records / methods | Later | Same |
| Full type diagnostics | **Parked** | Host remains source of truth |
| Emit performance (string building) | **Later** | Stage compile times hurt daily workflow |
| Native emit size (self-host tc.te) | **Later** | stage0→tc.te OOMs cc1 on Windows; host builds stage1 until emit is compact |
| Feature parity with host | **Parked** | Never a goal by itself |

### 3.3 Explicit lift triggers (checklist)

Update **`tc.te`** at these milestones:

```
[x] T1  CLI argv: source + optional output; default ~/.terse/out/<stem> (fallback env)
[x] T2  native env get (terse_env) + env set (terse_env_set) for env(k)=v
[ ] T3  When lists other than [long]/[str] appear in native-compiled demos:
        typed List_* runtime + list_new/get/push/len/concat emit
[ ] T4  When maps are required under native: Map_* runtime + put/get/keys
[ ] T5  When multi-file programs must compile under native: minimal use resolver
        (single search path is enough at first)
[ ] T6  When en/rec are required under native: tags + field access emit only
        (no need for full host pattern exhaustiveness)
[x] T7  Smaller native emit (mitigations)
        - Double-emit fixed for strcmp / +
        - compile_file writes .c in chunks (io.out + io.append) + emit_fn_body for entry
        - fs_append_text in host + native runtime
        - Full tc.te under stage0 may still stress cc1; prefer `make tcc1` until measured OK
[x] T8  make bootstrap-verify target: stage0 smoke tiny .te (full tc.te may OOM)
```

### 3.4 What native does **not** need soon

- Full TypeChecker parity with host
- `std.tst` runner logic (tests stay on host)
- Trait/impl elaboration beyond what bootstrap needs
- LSP / package registry

### 3.5 Workflow for a native update

```
1. Feature stable on host (tests green)
2. Add minimal scan/parse/emit or runtime in tc.te
3. Rebuild: tersec.py build tc.te -o out/tc-stage0
4. ./out/tc-stage0   # or with argv once T1 lands
5. Confirm stage1 binary compiles a smoke .te
6. Note the lift in this roadmap (check off T*)
```

---

## 4. Medium-term (usable beyond the author)

1. **LSP / editor basics** — syntax highlight + diagnostics from host (or external wrapper)  
   - **`tc.te`:** not involved
2. **Package layout / tpm** — deferred; design in `tpm_spec.md` (install into `lib/`, lockfile, no compiler changes)
   - **`tc.te`:** not involved until a Terse-written tpm needs HTTP/hash
3. **More std (optional)** — only with SPEC entries  
   - **`tc.te`:** runtime stubs only when native must link them
4. **Ownership / borrowing** — Parked  
5. **Full generics / higher-order with capture** — Limited → expand only with tests  
   - **`tc.te`:** Parked

---


## 5. Suggested execution order (checklist)

```
Host:
[x] 1.1  env get/set + tests
[x] 1.2  return-type and list-element mismatch diagnostics
[x] 1.3  SPEC/std freeze note (short section)
[x] 1.4  empty list / map edge-case tests
[x] 1.5  verify gate still green after each item
[x] 2.x  only after 1.x feels solid

Native (only at triggers in §3.3):
[x] T1   CLI argv source + output (host path is now the conformance reference)
[x] T2   env runtime/emit (after 1.1)
[ ] T3   typed lists under native (if demos need them)
[x] T8   bootstrap-verify make target
[x] T9   native: default out ~/.terse/out + link ~/.terse/out/lib/*.o when fresh
[ ] T4–T7 as needed — not by default
```

This checklist is intentionally conservative: it reflects the current baseline rather than a speculative future list. The host work in §1 is effectively complete; native lifts remain conditional on the triggers in §3.3.

---

## 6. Definition of “usable”

Terse is **usable** when:

1. A new file in `src/` + `tst/t_*.te` compiles and tests without hand-written C.
2. Unknown names and obvious type mismatches fail **before** gcc with readable messages.
3. Lists, maps, modules, and std.str/io/tst behave as SPEC says.
4. `make verify` is green on the reference host.

**Native is “good enough”** when:

1. `tc.te` still bootstraps stage0 → stage1 on the main platforms.
2. Smoke programs in the intended native set compile and run.
3. Gaps vs host are documented (this file), not accidental.

Ship host features that move the four usability needles; lift into **`tc.te` only at the triggers in §3**.
