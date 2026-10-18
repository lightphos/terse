(* ============================================================
   Terse 0.3 — grammar (aligned with SPEC.md / tersec.py host)
   ============================================================ *)


(* Program *)

<program>       ::= { <item> }

<item>          ::= <use-decl>
                  | <type-decl>
                  | <record-decl>
                  | <enum-decl>
                  | <trait-decl>
                  | <fix-decl>
                  | <fn-decl>
                  | <go-decl>


(* Modules, paths, visibility *)

<use-decl>      ::= "use" <use-item> { "," <use-item> }

<use-item>      ::= <path> [ "as" IDENT ]
                  | <path> "." "{" <use-item> { "," <use-item> } "}"
                  | <path> "." "*"

<path>          ::= IDENT { "." IDENT }

(* Visibility: optional "pub" before fn / rec / tr / fix.
   Enums (en) are public by default — no pub required to export.
   fix without pub is file-local (not imported by use). *)

<vis>           ::= "pub"


(* Declarations *)

<type-decl>     ::= [<vis>] "type" IDENT [ <type-params> ] "=" <type>

<record-decl>   ::= [<vis>] "rec" IDENT [ <type-params> ]
                    "{" [ <field> { "," <field> } [ "," ] ] "}"
                  | [<vis>] IDENT "{" [ <field> { "," <field> } [ "," ] ] "}"
                    (* bare "Point { ... }" sugar for rec *)

<enum-decl>     ::= [<vis>] "en" IDENT [ <type-params> ]
                    "{" [ <enum-variant> { "," <enum-variant> } [ "," ] ] "}"
                    (* default public for module export *)

<enum-variant>  ::= IDENT [ "(" [ <type> { "," <type> } [ "," ] ] ")" ]

<trait-decl>    ::= [<vis>] "tr" IDENT [ <type-params> ]
                    "{" { <trait-method> } "}"

<trait-method>  ::= "fn" IDENT <params> [ "->" <type> ]

<fn-decl>       ::= [<vis>] "fn" <fn-name> <params>
                    [ "->" <type> ] <fn-body>

<go-decl>       ::= "go" <fn-body>

<fix-decl>      ::= [<vis>] "fix" IDENT [ ":" <type> ] "=" <expr>
                    (* private/file-local by default; pub fix is exportable *)

<fn-name>       ::= IDENT [ "." IDENT ]   (* Point.method *)

<params>        ::= "(" [ <param> { "," <param> } [ "," ] ] ")"

<param>         ::= IDENT [ ":" <type> ]

<fn-body>       ::= "=" <expr>
                  | <block-expr>


(* Types *)

<type>          ::= IDENT [ <type-args> ]
                  | "fn" "(" [ <type> { "," <type> } [ "," ] ] ")"
                      [ "->" <type> ]
                  | "[" <type> "]"
                  | "{" <type> ":" <type> "}"
                  | "rec" "{" [ <field> { "," <field> } [ "," ] ] "}"
                  | "(" ")"
                  | "(" <type> "," <type> { "," <type> } [ "," ] ")"

<field>         ::= IDENT ":" <type>

<type-params>   ::= "[" IDENT { "," IDENT } [ "," ] "]"

<type-args>     ::= "[" <type> { "," <type> } [ "," ] "]"


(* Expressions *)

<expr>          ::= <pipe-expr>
                  | <ternary-expr>

(* Ternary is parsed with ? : at the same level as other expr forms in the host *)

<ternary-expr>  ::= <pipe-expr> "?" <expr> ":" <expr>

<pipe-expr>     ::= <or-expr> { "|>" <or-expr> }

<or-expr>       ::= <and-expr> { "||" <and-expr> }

<and-expr>      ::= <cmp-expr> { "&&" <cmp-expr> }

<cmp-expr>      ::= <add-expr> { <cmp-op> <add-expr> }

<cmp-op>        ::= "==" | "!=" | "<" | ">" | "<=" | ">="

<add-expr>      ::= <mul-expr> { ( "+" | "-" ) <mul-expr> }
                    (* + also: str concat, list concat/push *)

<mul-expr>      ::= <unary-expr> { ( "*" | "/" | "%" ) <unary-expr> }

<unary-expr>    ::= ( "!" | "-" ) <unary-expr>
                  | <postfix-expr>

<postfix-expr>  ::= <primary-expr> { <postfix-op> }

<postfix-op>    ::= "." IDENT
                  | "(" [ <expr> { "," <expr> } [ "," ] ] ")"
                  | "[" <expr> "]"
                  | "?"

<primary-expr>  ::= INT
                  | FLOAT
                  | STRING
                  | "true"
                  | "false"
                  | IDENT
                  | "(" ")"
                  | "(" <expr> ")"
                  | "(" <expr> "," <expr> { "," <expr> } [ "," ] ")"
                  | "[" [ <expr> { "," <expr> } [ "," ] ] "]"
                  | <map-literal>
                  | <record-literal>
                  | <lambda-expr>
                  | <if-expr>
                  | <match-expr>
                  | <loop-expr>
                  | <block-expr>
                  | <ret-expr>
                  | <jump-expr>

<map-literal>   ::= "{:" "}"
                  | "{" <expr> ":" <expr> { "," <expr> ":" <expr> } [ "," ] "}"

<record-literal> ::= IDENT "{" [ IDENT ":" <expr>
                                  { "," IDENT ":" <expr> } [ "," ] ] "}"

<lambda-expr>   ::= "|" [ <param> { "," <param> } [ "," ] ] "|" <fn-body>


(* Control flow *)

<if-expr>       ::= "if" <expr> <block-expr>
                    { "else" "if" <expr> <block-expr> }
                    [ "else" <block-expr> ]
                  | "if" <expr> "{" { <match-arm> } "}"
                    [ "else" <block-expr> ]

(* Match-style if when body contains => arms.
   Catch-all: "_ => expr" or trailing else block. *)

<match-expr>    ::= "match" <expr> "{" { <match-arm> } "}"

<match-arm>     ::= <pattern> [ "if" <expr> ] "=>" <expr>

<pattern>       ::= "_"
                  | IDENT
                  | IDENT "." IDENT [ "(" [ <pattern> { "," <pattern> } [ "," ] ] ")" ]
                  | INT
                  | FLOAT
                  | STRING
                  | "true"
                  | "false"
                  | "(" ")"
                  | "(" <pattern> "," <pattern> { "," <pattern> } [ "," ] ")"
                  | "[" [ <pattern> { "," <pattern> } [ "," ] ] "]"
                  | <record-pattern>

<record-pattern> ::= IDENT "{" [ <field-pattern>
                                  { "," <field-pattern> } [ "," ] ] "}"

<field-pattern> ::= IDENT [ ":" <pattern> ]

<loop-expr>     ::= "lp" IDENT ":" <expr> <block-expr>
                  | "lp" IDENT "=" <expr> ";" <expr> ";" [ <expr> ] <block-expr>
                  | "lp" <binding> ";" [ <expr> ] ";" [ <expr> ] <block-expr>
                  | "lp" <expr> <block-expr>
                  | "while" <expr> <block-expr>

<ret-expr>      ::= "ret" [ <expr> ]

<jump-expr>     ::= "brk" [ <expr> ]
                  | "skip"


(* Blocks, bindings, assignment *)

<block-expr>    ::= "{" { <stmt> } [ <expr> ] "}"

<stmt>          ::= <binding>
                  | <assign-stmt>
                  | <ret-expr>
                  | <jump-expr>
                  | <expr>

<binding>       ::= "val" IDENT [ ":" <type> ] "=" <expr>
                  | "var" IDENT [ ":" <type> ] "=" <expr>

<assign-stmt>   ::= <postfix-expr> <assign-op> <expr>

<assign-op>     ::= "=" | "+=" | "-=" | "*=" | "/=" | "%="


(* ------------------------------------------------------------
   Notes (host semantics — see SPEC.md)
   - std.str / std.io / std.tst are library surfaces, not grammar productions
   - tst.eq / tst.ne are std.tst calls
   - Test layout: tst/**/t_*.te auto-runs zero-arg fns
   - Module search: parallel tst/usage ↔ src/usage
   ------------------------------------------------------------ *)
