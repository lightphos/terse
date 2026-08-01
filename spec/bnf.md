# Terse language grammar (BNF)

Derived directly from the lexer and recursive-descent parser in `tersec.py`.

```bnf
<program>       ::= { <use-decl> | <rec-decl> | <type-decl>
                     | <fn-decl>  | <go-decl>  | <let-stmt> | <expr-stmt> }

<use-decl>      ::= "use" <path> { "," <path> } [ ";" ]
<path>          ::= IDENT { "." IDENT }

<type-decl>     ::= "type" IDENT "=" <type> [ ";" ]

<rec-decl>      ::= "rec" IDENT "{" [ <field> { "," <field> } [ "," ] ] "}"
<field>         ::= IDENT ":" <type>

<fn-decl>       ::= "fn" IDENT <params> [ "->" <type> ] [ "=" ] <expr>

<go-decl>       ::= "go" <expr>

<let-stmt>      ::= "let" IDENT [ ":" <type> ] "=" <expr> [ ";" ]
<expr-stmt>     ::= <expr> [ ";" ]

<params>        ::= "(" [ <param> { "," <param> } ] ")"
<param>         ::= IDENT [ ":" <type> ]

<type>          ::= IDENT
                   | "fn" "(" [ <type> { "," <type> } ] ")" [ "->" <type> ]
                   | "[" <type> "]"
                   | "{" [ IDENT ":" <type> { "," IDENT ":" <type> } ] "}"

<expr>          ::= <or-expr>
<or-expr>       ::= <and-expr>  { "||" <and-expr> }
<and-expr>      ::= <cmp-expr>  { "&&" <cmp-expr> }
<cmp-expr>      ::= <add-expr>  { ("==" | "!=" | "<" | ">" | "<=" | ">=") <add-expr> }
<add-expr>      ::= <mul-expr>  { ("+" | "-") <mul-expr> }
<mul-expr>      ::= <unary-expr>{ ("*" | "/" | "%") <unary-expr> }
<unary-expr>    ::= ("!" | "-") <unary-expr> | <postfix-expr>

<postfix-expr>  ::= <primary-expr> { <postfix-op> }
<postfix-op>    ::= "." IDENT                                  (* member access   *)
                   | "{" <record-fields> "}"                   (* record literal, only after Var/Member *)
                   | "(" [ <expr> { "," <expr> } ] ")" [ <http-routes> ]   (* call, +routes if http.serve(...) *)
                   | "[" <expr> "]"                             (* index            *)

<primary-expr>  ::= INT | "true" | "false" | STRING | IDENT
                   | "(" <expr> ")"
                   | <list-lit>
                   | <lambda-expr>
                   | <block-expr>
                   | <if-expr>

<list-lit>      ::= "[" [ <expr> { "," <expr> } ] "]"
<lambda-expr>   ::= "|" [ <param> { "," <param> } ] "|" <expr>
<if-expr>       ::= "if" <expr> <expr> [ "else" <expr> ]

<block-expr>    ::= "{" { <block-stmt> } "}"
<block-stmt>    ::= ( "let" IDENT [ ":" <type> ] "=" <expr> | <expr> ) [ ";" ]

<record-fields> ::= [ IDENT ":" <expr> { "," IDENT ":" <expr> } ]

<http-routes>   ::= "{" { <route> } "}"
<route>         ::= IDENT STRING "=>" <expr> [ ";" ]
                     (* IDENT must be one of GET POST PUT DELETE PATCH, case-insensitive *)
```

## Notes

- **Precedence** (loosest to tightest): `||` → `&&` → equality/relational → `+ -` → `* / %` → unary `! -` → postfix (`.`, `()`, `[]`, `{}`) → primary. This matches the `parse_or → parse_and → parse_cmp → parse_add → parse_mul → parse_unary → parse_postfix → parse_primary` call chain.
- **`let` is expression-scoped**, not a statement: inside a block, `let x = v; rest` desugars to a `LetExpr` wrapping the remainder of the block, so `let` always has a body.
- **`{ ... }` is context-sensitive**: after a bare `if`/lambda body it's a block; directly after a `Var`/`Member` in postfix position it's a record literal instead (e.g. `Point{x: 1, y: 2}`); after `http.serve(port)` it's a route table.
- **Sequencing**: consecutive expression statements in a block (not the last one) are desugared as `let _ = expr in rest`.
- **Records** (`type`) are parsed but their shape is discarded — `type Foo = {...}` only checks syntax.
- **Comments**: `// line` and `/* block */`, stripped by the lexer, not part of the grammar above.
- **`main`/`go` synthesis**: if no `fn main` exists, a trailing top-level `go <expr>` or top-level statements become the body of a synthesized `main`.