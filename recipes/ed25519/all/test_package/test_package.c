#include <ed25519.h>

#include <stdio.h>
#include <string.h>

int main(void) {
    ed25519_secret_key sk;
    ed25519_public_key pk;
    ed25519_signature sig;
    const unsigned char msg[] = "conan";

    memset(sk, 1, sizeof(sk));
    ed25519_publickey(sk, pk);
    ed25519_sign(msg, sizeof(msg), sk, pk, sig);
    if (ed25519_sign_open(msg, sizeof(msg), pk, sig) != 0) {
        fprintf(stderr, "ed25519: signature verification failed\n");
        return 1;
    }

    printf("ed25519: signature verified\n");
    return 0;
}
