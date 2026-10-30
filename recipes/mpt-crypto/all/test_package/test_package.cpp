#include <utility/mpt_utility.h>

#include <cstdint>
#include <iostream>

int main() {
    std::uint8_t privkey[kMPT_PRIVKEY_SIZE];
    std::uint8_t pubkey[kMPT_PUBKEY_SIZE];
    std::uint8_t blinding_factor[kMPT_BLINDING_FACTOR_SIZE];
    std::uint8_t ciphertext[kMPT_ELGAMAL_TOTAL_SIZE];
    std::uint64_t amount = 0;

    if (mpt_generate_keypair(privkey, pubkey) != 0 ||
        mpt_generate_blinding_factor(blinding_factor) != 0 ||
        mpt_encrypt_amount(42, pubkey, blinding_factor, ciphertext) != 0 ||
        mpt_decrypt_amount(ciphertext, privkey, &amount, 0, 100) != 0 ||
        amount != 42) {
        std::cerr << "mpt-crypto: encrypt/decrypt round trip failed\n";
        return 1;
    }

    std::cout << "mpt-crypto: decrypted " << amount << '\n';
    return 0;
}
