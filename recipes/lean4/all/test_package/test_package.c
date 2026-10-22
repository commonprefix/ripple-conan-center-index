#include <lean/lean.h>
#include <stdio.h>

/* Declared by Lean's generated C rather than by lean.h. */
extern void lean_initialize_runtime_module(void);

int main(void) {
    lean_initialize_runtime_module();
    lean_object *s = lean_mk_string("lean4");
    printf("%s: %u bytes\n", lean_string_cstr(s), (unsigned)lean_string_size(s));
    lean_dec(s);
    return 0;
}
