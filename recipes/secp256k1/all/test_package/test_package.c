#include <secp256k1.h>

#include <stdio.h>
#include <string.h>

int main(void) {
    secp256k1_context* ctx = secp256k1_context_create(SECP256K1_CONTEXT_NONE);
    unsigned char seckey[32];
    secp256k1_pubkey pubkey;
    int ok;

    memset(seckey, 1, sizeof(seckey));
    ok = secp256k1_ec_seckey_verify(ctx, seckey) &&
         secp256k1_ec_pubkey_create(ctx, &pubkey, seckey);
    secp256k1_context_destroy(ctx);
    if (!ok) {
        fprintf(stderr, "secp256k1: failed to create a public key\n");
        return 1;
    }

    printf("secp256k1: public key created\n");
    return 0;
}
