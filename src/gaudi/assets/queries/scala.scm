(package_clause
  name: (package_identifier) @name) @definition.module

(trait_definition
  name: (identifier) @name) @definition.interface

(class_definition
  name: (identifier) @name) @definition.class

(object_definition
  name: (identifier) @name) @definition.object

(function_definition
  name: (identifier) @name) @definition.function

(call_expression
  (identifier) @name) @reference.call
