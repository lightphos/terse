# Current review of the Terse repo

This review reflects the state of the repository as it exists now: the host compiler is active, the test suite is green, and the remaining work is mostly about semantics, documentation consistency, and compiler ergonomics rather than missing base features.

## What is already in good shape

- The host compiler under `compiler/tersec/` is a coherent implementation pipeline: lexer → parser → type checker → C codegen.
- The project has a real, passing test baseline: `make tst` succeeds.
- Core language features are implemented and exercised: lists, maps, enums, records, traits, generics, methods, `use`, `pub`, pattern matching, and the standard library surface used by the tests.
- The docs are now aligned on the actual repository layout: the grammar file is `spec/TERSE_BNF.md`, not a stale `spec/bnf.md` path.
- The project explicitly treats the host compiler as the conformance reference, which is a sound strategy for a repo with a native C backend and a bootstrap compiler.


## Remaining gaps and inconsistencies

| Area | Status | Why it still matters |
|------|--------|---------------------|
| Semantics of container aliasing | Open | Lists/maps are treated as runtime values, but the repo does not specify the aliasing model clearly enough for soundness discussions. |
| `env()` semantics | Open | The setter/getter behavior is implemented but the spec does not define process scope, persistence rules, or return semantics precisely. |
| Trait dispatch model | Open | Monomorphization is used, but the exact dispatch story for generic traits and structural satisfaction is still intentionally fuzzy. |
| Generic pattern names | Open | The repo still relies on specialized names such as `Opt__long.Some(x)` in some contexts; this is a real user-facing mismatch with the intended surface. |
| Lambda capture semantics | Open | Closure capture is on the edge of the language contract and not fully pinned down in the spec. |
| Error recovery | Open | The compiler aborts on the first real failure, which keeps implementation simple but makes diagnostics weaker than a production compiler. |
| No IR / backend abstraction | Open | The host compiler emits C directly. This is workable, but it makes future backends and optimization work harder. |
| Doc-to-code drift risk | Open | The repo is healthy now, but the project still has a nontrivial amount of docs and implementation detail spread across multiple files; extra discipline is needed to keep them aligned. |

## Concrete issues worth fixing next

1. Make the value semantics explicit
   - Document whether list/map values are copied, shared, refcounted, or otherwise alias-safe.
   - Define what happens when a value is assigned or mutated through an alias.

2. Finish the `env()` contract
   - State whether `env("K")` reads from process environment and whether `env("K") = "v"` mutates only the current process.
   - Clarify the return value of the setter and any failure behavior.

3. Tighten generic trait semantics
   - Decide whether trait dispatch is monomorphized, vtable-based, or adapter-based.
   - Describe the expected naming strategy for generated generic constructors and match patterns.

4. Put closure capture on the spec roadmap
   - Document supported captures, restrictions, and whether nested functions can close over mutable locals.

5. Keep the docs in one authoritative flow
   - README, AGENTS, roadmap, and the language spec should all point to the same canonical file names and status.

## Bottom line

The repo has reached a meaningful baseline: the compiler works, the tests pass, and the core shape of the language is stable. The big remaining challenges are not “is the language incomplete?” but “are the semantics and docs precise enough for a real language user and contributor base?”

The most important open work is semantic clarity around aliases, trait dispatch, and environment behavior, followed by tighter documentation discipline.
