#include <wasm_export.h>

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>

/* The package is built with WAMR_BH_LOG=wamr_log_to_rippled, so the consumer
   has to provide the log sink. */
void wamr_log_to_rippled(uint32_t log_level, const char* file, int line, const char* fmt, ...) {
    va_list args;
    (void)log_level;
    (void)file;
    (void)line;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
}

int main(void) {
    uint32_t major, minor, patch;

    if (!wasm_runtime_init()) {
        fprintf(stderr, "wasm-xrplf: failed to initialize the runtime\n");
        return 1;
    }
    wasm_runtime_get_version(&major, &minor, &patch);
    wasm_runtime_destroy();

    printf("wasm-xrplf: WAMR %u.%u.%u\n", major, minor, patch);
    return 0;
}
