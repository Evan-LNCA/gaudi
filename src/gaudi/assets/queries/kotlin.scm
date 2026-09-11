(class_declaration
  (type_identifier) @name) @definition.class

(object_declaration
  (type_identifier) @name) @definition.class

(function_declaration
  (simple_identifier) @name) @definition.function

(type_alias
  (type_identifier) @name) @definition.type

(call_expression
  (simple_identifier) @name) @reference.call
