(* ============================================================
   Terse 0.2 — complete grammar
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

<path>          ::= IDENT { "." IDENT }

<vis>           ::= "pub"


(* Declarations *)

<type-decl>     ::= [<vis>] "type" IDENT [ <type-params> ] "=" <type>

<record-decl>   ::= [<vis>] "rec" IDENT [ <type-params> ]
                    "{" [ <field> { "," <field> } [ "," ] ] "}"

<enum-decl>     ::= [<vis>] "en" IDENT [ <type-params> ]
                    "{" [ <enum-variant> { "," <enum-variant> } [ "," ] ] "}"

<enum-variant>  ::= IDENT [ "(" [ <type> { "," <type> } [ "," ] ] ")" ]

<trait-decl>    ::= [<vis>] "tr" IDENT [ <type-params> ]
                    "{" { <trait-method> } "}"

<trait-method>  ::= "fn" IDENT <params> [ "->" <type> ]

<fn-decl>       ::= [<vis>] "fn" <fn-name> <params>
                    [ "->" <type> ] <fn-body>

<go-decl>       ::= "go" <fn-body>

<fix-decl>    ::= [<vis>] "fix" IDENT [ ":" <type> ] "=" <expr>

<fn-name>       ::= IDENT [ "." IDENT ]

<params>        ::= "(" [ <param> { "," <param> } [ "," ] ] ")"

<param>         ::= IDENT [ ":" <type> ]

<fn-body>       ::= "=" <expr>
                  | <block-expr>


(* Types *)

<type>          ::= IDENT [ <type-args> ]
                  | "fn" "(" [ <type> { "," <type> } [ "," ] ] ")"
                      [ "->" <type> ]
                  | "[" <type> "]"
                  | "rec" "{" [ <field> { "," <field> } [ "," ] ] "}"
                  | "(" ")"
                  | "(" <type> "," <type> { "," <type> } [ "," ] ")"

<field>         ::= IDENT ":" <type>

<type-params>   ::= "[" IDENT { "," IDENT } [ "," ] "]"

<type-args>     ::= "[" <type> { "," <type> } [ "," ] "]"


(* Expressions *)

<expr>          ::= <pipe-expr>

<pipe-expr>     ::= <or-expr> { "|>" <or-expr> }

<or-expr>       ::= <and-expr> { "||" <and-expr> }

<and-expr>      ::= <cmp-expr> { "&&" <cmp-expr> }

<cmp-expr>      ::= <add-expr> { <cmp-op> <add-expr> }

<cmp-op>        ::= "=="
                  | "!="
                  | "<"
                  | ">"
                  | "<="
                  | ">="

<add-expr>      ::= <mul-expr> { ( "+" | "-" ) <mul-expr> }

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
                  | <record-literal>
                  | <lambda-expr>
                  | <if-expr>
                  | <match-expr>
                  | <loop-expr>
                  | <block-expr>
                  | <ret-expr>
                  | <jump-expr>

<record-literal> ::= IDENT "{" [ IDENT ":" <expr>
                                  { "," IDENT ":" <expr> } [ "," ] ] "}"

<lambda-expr>   ::= "|" [ <param> { "," <param> } [ "," ] ] "|" <fn-body>


(* Control flow *)

<if-expr>       ::= "if" <expr> <block-expr>
                    { "else" "if" <expr> <block-expr> }
                    [ "else" <block-expr> ]
                  | "if" <expr> "{" { <match-arm> } "}"
                    [ "else" <block-expr> ]

(* Match-style if is used when the body contains => arms.
   Catch-all: "_ => expr" inside the arms, or a trailing else block. *)

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

<assign-op>     ::= "="
                  | "+="
                  | "-="
                  | "*="
                  | "/="
                  | "%="
