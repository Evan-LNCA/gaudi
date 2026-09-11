(function_declaration
  name: (identifier) @name) @definition.function

(generator_function_declaration
  name: (identifier) @name) @definition.function

(class_declaration
  name: (_) @name) @definition.class

(method_definition
  name: (property_identifier) @name) @definition.method

(interface_declaration
  name: (type_identifier) @name) @definition.interface

(type_alias_declaration
  name: (type_identifier) @name) @definition.type

(enum_declaration
  name: (identifier) @name) @definition.enum

(call_expression
  function: (identifier) @name) @reference.call
