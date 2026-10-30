#include <lean/lean.h>
#include <stdio.h>

/* Declared by Lean's generated C rather than by lean.h. */
extern void lean_initialize(void);

/* Module initializer of Qq's root module, a small member of the bundle that
 * depends only on Lean itself. Pulls objects out of libmathlib4.a and resolves
 * their references into libleanshared. */
extern lean_object *initialize_Qq_Qq(uint8_t builtin);

int main(void) {
    lean_initialize();
    lean_object *res = initialize_Qq_Qq(1);
    if (!lean_io_result_is_ok(res)) {
        lean_io_result_show_error(res);
        lean_dec(res);
        return 1;
    }
    lean_dec_ref(res);
    lean_io_mark_end_initialization();
    puts("mathlib4: Qq initialized");
    return 0;
}
