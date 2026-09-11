(struct_item
  name: (type_identifier) @name) @definition.class

(enum_item
  name: (type_identifier) @name) @definition.class

(union_item
  name: (type_identifier) @name) @definition.class

(type_item
  name: (type_identifier) @name) @definition.class

(declaration_list
  (function_item
    name: (identifier) @name) @definition.method)

(function_item
  name: (identifier) @name) @definition.function

(trait_item
  name: (type_identifier) @name) @definition.interface

(mod_item
  name: (identifier) @name) @definition.module

(macro_definition
  name: (identifier) @name) @definition.macro

(call_expression
  function: (identifier) @name) @reference.call

(call_expression
  function: (field_expression
    field: (field_identifier) @name)) @reference.call

(macro_invocation
  macro: (identifier) @name) @reference.call
