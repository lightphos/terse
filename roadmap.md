# Terse Roadmap

Living plan for the next work items.  
**Reference compiler:** `tersec.py` (host) · **Grammar/spec:** `terse_bnf.md`, `SPEC.md` (0.3) · **Native:** `tc.te` (subset)

Status legend: **Done** · **Next** · **Later** · **Parked**

---

## 0. Current baseline (Done)

- Host compile to C (`gcc`/`clang -O0 -std=c11`)
- Core syntax: `val`/`var`/`fix`, `fn`, `go`, `if`/`else`, ternary `? :`, `lp` (C-style + for-in), `brk`/`skip`
- Types: `i64`/`long`, `i32`/`int`, `i16`/`short`, `i8`/`char`, `u8`–`u64`, `f32`/`float`, `f64`/`double`, `bool`, `str`
- Width-accurate lists: `[i32]`, `[f64]`, `[str]`, … + concat/push/`len`
- Records (`rec`), enums (`en`, public by default), traits (`tr`, limited)
- Pattern `if` / `match`, modules (`use`/`pub`), parallel `tst/` ↔ `src/`
- `std.str`, `std.io`, `std.tst` (`eq` / `ne`)
- Hard diagnostics: unknown name/function, type mismatch (abort before gcc)
- Bootstrap path for `tc.te` (stage0 → stage1)
- Docs: SPEC 0.3, `terse_bnf.md`, unit suite `test_compiler.py`

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

### 1.1 Environment API  **Next**
```terse
env("KEY") = "value"   // set
ret env("KEY")         // get
```
- Runtime: `getenv` / `setenv` (or platform equivalent)
- Type: `str` in / `str` out; missing key → `""` or documented sentinel
- Tests: `src/` demo + `tst/t_env.te`
- **`tc.te`:** update when bootstrap or native demos need env (e.g. `TERSE_SOURCE` already used); add runtime helpers + parse/emit for `env(...)` and assignment form once host is stable

### 1.2 Richer type diagnostics  **Next**
- Return-type vs `ret` value mismatches (with line:col when available)
- List element type mismatches (`[i32]` vs `[f64]`)
- Clear messages for bad `use` paths / missing modules
- Prefer hard errors over silent `i64` defaults where practical
- **`tc.te`:** **do not** mirror full diagnostics yet; host remains the conformance checker. Revisit only if native is used as the daily compiler and opaque C failures dominate

### 1.3 Freeze std surface  **Next**
Document and lock only what the host implements:

| Module   | Surface |
|----------|---------|
| `std.str` | `has`, `starts`, `ends`, `trim`, `up`, `low`, `parse`, `split`, `join` |
| `std.io`  | `in`, `out` (read/write text) |
| `std.tst` | `eq`, `ne`, (optional `chk` / `report`) |

No silent expansion of std without a SPEC/BNF note.

- **`tc.te`:** no code change for a freeze note; when implementing std in native, only emit calls the native runtime already has (`fs_read_text` / `fs_write_text`, string helpers). Do not invent std modules inside `tc.te` ahead of host

### 1.4 List / map edge cases  **Next**
- Empty typed lists `var xs: [i32] = []` everywhere stable
- Map `{:}` / `{str:i64}` put/get/keys consistent with docs
- Index bounds messages (already exit; make message consistent)
- **`tc.te`:** lift **typed list runtime + emit** when native must compile programs that use `[i32]`/`[f64]` (not only `List`/`i64`). Until then, native may keep i64-only lists. Update when a bootstrap or demo fails without width-accurate lists

### 1.5 Tooling quality gate  **Next**
- `make verify` = `test_compiler.py` + selected `tst/*.te`
- `test.sh` continues to list failed files
- Keep unknown-name / mismatch tests in the suite
- **`tc.te`:** optional later — a `make bootstrap-verify` that rebuilds stage0→stage1 and compiles a small smoke set with the native binary

---

## 2. Near-term language (after §1)

### 2.1 String interpolation or format helper  **Later**
Minimal option (prefer one, not both):
- `fmt("x={x} y={y}")` style, **or**
- Keep `+` concat only and document it as the official path
- **`tc.te`:** only after host lands and SPEC freezes the choice; emit as concat or a single runtime `fmt` helper

### 2.2 Better errors for C backend failures  **Later**
- Surface first gcc/clang error line mapped to terse source when possible
- Reduce “C compile failed” without context
- **`tc.te`:** low priority; native already prints `TC_GCC_ERROR`. Improve only if users compile primarily with `tc`

### 2.3 Public API defaults review  **Later**
- Confirm: `en` public; `fn`/`rec`/`tr`/`fix` private unless `pub`
- SPEC + examples stay aligned
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
| CLI: argv source + output (not only `TERSE_SOURCE`/`TERSE_OUTPUT`) | **Next** | Daily native use is awkward without args |
| `env` get/set | After host §1.1 | Native demos or bootstrap need process env beyond the two TERSE_* vars |
| Width-accurate lists / maps | After host §1.4 stable | Native must compile non-i64 list programs |
| Numeric types beyond i64 | Later | Same as lists — when demos need `i32`/`f64` in native path |
| Modules `use` / `pub` | Later | Multi-file native compiles are required |
| Enums + pattern `if` | Later | Bootstrap or demos need `en` under native |
| Records / methods | Later | Same |
| Full type diagnostics | **Parked** | Host remains source of truth |
| Emit performance (string building) | **Later** | Stage compile times hurt daily workflow |
| Feature parity with host | **Parked** | Never a goal by itself |

### 3.3 Explicit lift triggers (checklist)

Update **`tc.te`** at these milestones:

```
[ ] T1  CLI argv: first arg = source, second = output (fallback to env)
[ ] T2  After host env API: native runtime env_get / env_set + emit
[ ] T3  When lists other than [i64]/[str] appear in native-compiled demos:
        typed List_* runtime + list_new/get/push/len/concat emit
[ ] T4  When maps are required under native: Map_* runtime + put/get/keys
[ ] T5  When multi-file programs must compile under native: minimal use resolver
        (single search path is enough at first)
[ ] T6  When en/rec are required under native: tags + field access emit only
        (no need for full host pattern exhaustiveness)
[ ] T7  If stage compile is too slow: switch emit to buffered/rope-style
        string building (not before T1–T3 if those are blocking)
[ ] T8  make bootstrap-verify target: stage0→stage1 + smoke .te files
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
2. **Package layout** — optional `terse.mod` or directory convention beyond path `use`  
   - **`tc.te`:** only if native multi-file (T5) is already real
3. **More std (optional)** — only with SPEC entries  
   - **`tc.te`:** runtime stubs only when native must link them
4. **Ownership / borrowing** — Parked  
5. **Full generics / higher-order with capture** — Limited → expand only with tests  
   - **`tc.te`:** Parked

---

## 5. Explicitly not in the next set

- SQL / DB runtime (removed by design)
- Matching Python feature parity for every AST node in `tc.te`
- Changing `val`/`var` back to `let`/`mut`
- Free Grok API or editor plugins as language requirements

---

## 6. Suggested execution order (checklist)

```
Host:
[ ] 1.1  env get/set + tests
[ ] 1.2  return-type and list-element mismatch diagnostics
[ ] 1.3  SPEC/std freeze note (short section)
[ ] 1.4  empty list / map edge-case tests
[ ] 1.5  verify gate still green after each item
[ ] 2.x  only after 1.x feels solid

Native (only at triggers in §3.3):
[ ] T1   CLI argv source + output
[ ] T2   env runtime/emit (after 1.1)
[ ] T3   typed lists under native (if demos need them)
[ ] T8   bootstrap-verify make target
[ ] T9   native: default out ~/.terse/out + link ~/.terse/out/lib/*.o when fresh
[ ] T4–T7 as needed — not by default
```

---

## 7. Definition of “usable”

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
