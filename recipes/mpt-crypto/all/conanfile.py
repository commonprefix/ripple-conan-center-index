from conan import ConanFile, tools
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import copy, get
import os

required_conan_version = ">=2.0.0"


class MptCryptoConan(ConanFile):
    name = "mpt-crypto"
    description = "MPT-Crypto: Cryptographic Primitives for Confidential Assets"
    url = "https://github.com/XRPLF/mpt-crypto"
    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "tests": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
        "tests": False,
    }

    def requirements(self):
        self.requires("openssl/[>=3.5 <4]")
        # The public headers include <secp256k1.h>
        self.requires("secp256k1/0.7.1", transitive_headers=True)

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def layout(self):
        cmake_layout(self, src_folder="src")
        self.folders.generators = "build/generators"

    def generate(self):
        tc = CMakeToolchain(self)
        tc.variables["ENABLE_TESTS"] = self.options.tests
        # Don't treat warnings as errors when built as a package/dependency:
        tc.variables["MPT_CRYPTO_WERROR"] = False
        tc.generate()

        deps = CMakeDeps(self)
        deps.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        # Copy headers
        copy(
            self,
            "*.h",
            src=os.path.join(self.source_folder, "include"),
            dst=os.path.join(self.package_folder, "include"),
            keep_path=True,
        )
        # Copy library files
        for ext in ["*.a", "*.lib", "*.dylib", "*.so*", "*.dll"]:
            copy(
                self,
                ext,
                src=self.build_folder,
                dst=os.path.join(self.package_folder, "lib"),
                keep_path=False,
            )

    def package_info(self):
        self.cpp_info.libs = ["mpt-crypto"]
        self.cpp_info.set_property("cmake_file_name", "mpt-crypto")
        self.cpp_info.set_property("cmake_target_name", "mpt-crypto::mpt-crypto")
