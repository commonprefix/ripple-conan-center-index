#include <wasm.h>

#include <stdio.h>

int main(void) {
    wasm_engine_t* engine = wasm_engine_new();
    wasm_store_t* store;

    if (engine == NULL) {
        fprintf(stderr, "wasmi: failed to create an engine\n");
        return 1;
    }
    store = wasm_store_new(engine);
    if (store == NULL) {
        fprintf(stderr, "wasmi: failed to create a store\n");
        wasm_engine_delete(engine);
        return 1;
    }
    wasm_store_delete(store);
    wasm_engine_delete(engine);

    printf("wasmi: engine and store created\n");
    return 0;
}
