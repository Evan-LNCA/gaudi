(call
  target: (identifier) @ignore
  (arguments (alias) @name)
  (#any-of? @ignore "defmodule" "defprotocol")) @definition.module

(call
  target: (identifier) @ignore
  (arguments
    [
      (identifier) @name
      (call target: (identifier) @name)
      (binary_operator
        left: (call target: (identifier) @name)
        operator: "when")
    ])
  (#any-of? @ignore "def" "defp" "defdelegate" "defguard" "defguardp" "defmacro" "defmacrop" "defn" "defnp")) @definition.function

(call
  target: [
    (identifier) @name
    (dot right: (identifier) @name)
  ]) @reference.call
