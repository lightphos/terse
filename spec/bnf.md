# Terse parser grammar (BNF)

This grammar describes syntax accepted by the Python reference parser in
`compiler/tersec.py`. It does not imply that every accepted construct has full
type-checker or runtime support; see `SPEC.md` for status.

```bnf
<program>          ::= { <item> } <go-decl> { <item> }
<item>             ::= <use-decl> | <type-decl> | <record-decl>
                                         | <trait-decl> | <fn-decl> | <pub-fn-decl>

<go-decl>          ::= "go" ( "(" ")" | <expr> )
<pub-fn-decl>      ::= "pub" <fn-decl>
<fn-decl>          ::= "fn" <fn-name> <params> [ "->" <type> ] [ "=" ] <expr>
<fn-name>          ::= IDENT [ "." IDENT ]
<params>           ::= "(" [ <param> { "," <param> } ] ")"
<param>            ::= IDENT [ ":" <type> ]

<use-decl>         ::= "use" <use-spec> { "," <use-spec> } [ ";" ]
<use-spec>         ::= <path> [ "as" IDENT ]
                                         | <module-path> "." IDENT [ "as" IDENT ]
<path>             ::= IDENT { ( "." | "/" ) IDENT }
<module-path>      ::= IDENT { ( "." | "/" ) IDENT }

<type-decl>        ::= "type" IDENT "=" <type> [ ";" ]
<record-decl>      ::= [ "rec" | "struct" ] IDENT
                       "{" [ <field> { "," <field> } ] "}"
<field>            ::= IDENT ":" <type>
<trait-decl>       ::= "tr" IDENT "{" { <trait-method> [ ";" ] } "}"
<trait-method>     ::= "fn" IDENT <params> [ "->" <type> ]

<type>             ::= IDENT
                                         | "fn" "(" [ <type> { "," <type> } ] ")"
                                             [ "->" <type> ]
                                         | "[" <type> "]"
                                         | "{" [ <field> { "," <field> } [ "," ] ] "}"

<expr>             ::= <assign-expr>
<assign-expr>      ::= <or-expr> [ "=" <assign-expr> ]
<or-expr>          ::= <and-expr> { "||" <and-expr> }
<and-expr>         ::= <cmp-expr> { "&&" <cmp-expr> }
<cmp-expr>         ::= <add-expr>
                                             { ( "==" | "!=" | "<" | ">" | "<=" | ">=" ) <add-expr> }
<add-expr>         ::= <mul-expr> { ( "+" | "-" ) <mul-expr> }
<mul-expr>         ::= <unary-expr> { ( "*" | "/" | "%" ) <unary-expr> }
<unary-expr>       ::= ( "!" | "-" ) <unary-expr> | <postfix-expr>

<postfix-expr>     ::= <primary-expr> { <postfix-op> }
<postfix-op>       ::= "." IDENT
                                         | "{" <record-fields> "}"
                                         | "(" [ <expr> { "," <expr> } ] ")" [ <http-routes> ]
                                         | "[" <expr> "]"
<record-fields>    ::= [ IDENT ":" <expr> { "," IDENT ":" <expr> } ]

<primary-expr>     ::= INT | "true" | "false" | STRING | IDENT
                                         | <ret-expr> | "(" <expr> ")" | <list-lit>
                                         | <lambda-expr> | <block-expr> | <if-expr> | <loop-expr>
<ret-expr>         ::= "ret" [ <expr> ]
<list-lit>         ::= "[" [ <expr> { "," <expr> } [ "," ] ] "]"
<lambda-expr>      ::= "|" [ <param> { "," <param> } ] "|" <expr>
<if-expr>          ::= "if" <expr> <expr> [ "else" <expr> ]
<loop-expr>        ::= "lp" <expr> <expr>
                                         | "lp" <loop-init> ";" [ <expr> ] ";" [ <expr> ] <expr>
<loop-init>        ::= <let-binding> | <expr>
<let-binding>     ::= "let" IDENT [ ":" <type> ] "=" <expr>

<block-expr>       ::= "{" { <block-stmt> [ ";" ] } "}"
<block-stmt>       ::= <let-binding> | <ret-expr> | <expr>

<http-routes>      ::= "{" { <route> [ ";" ] } "}"
<route>            ::= IDENT STRING "=>" <expr>
```

## Notes

- **Precedence** from loosest to tightest is `=` → `||` → `&&` → comparison → `+ -` → `* / %` → unary `! -` → postfix → primary. Assignment is right-associative.
- **Entrypoint**: exactly one `go` is required. It may appear among declarations. `fn main` is rejected, and top-level `let`/expression statements cannot accompany a `go` entrypoint; programs without `go` are rejected.
- **Imports**: dotted paths with two non-`std` segments are glob imports; a final dotted component on a longer path is a selected function; slash paths name a module namespace. `as` sets an explicit alias. This grammar shows the surface forms; resolution rules are in `SPEC.md`.
- **Records**: `rec Name { ... }`, `struct Name { ... }`, and bare `Name { ... }` declarations are accepted. A record literal is only accepted after a variable or member expression. Record type shapes are parsed but are not preserved as anonymous structural types.
- **Blocks**: an empty block evaluates to `0`. `let` and `ret` are accepted statements; the last expression supplies the block value. The current parser desugars earlier expression statements into bindings.
- **HTTP routes**: route blocks are a special form accepted only after `http.serve(...)`; methods are `GET`, `POST`, `PUT`, `DELETE`, or `PATCH` (case-insensitive).
- **Comments**: `//` and `/* ... */` comments are stripped by the lexer.
- `let mut`, `match`, `break`, `continue`, floats, unit literals, tuples, and `Option`/`Result` are not in the current parser grammar, even where they appear in the design/status sections of `SPEC.md`.