from conan import ConanFile, tools
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import get, copy, load
import os
import re

required_conan_version = ">=2.0.0"


class SecpConan(ConanFile):
    name = "secp256k1"
    description = "High-performance high-assurance C library for digital signatures and other cryptographic primitives on the secp256k1 elliptic curve."
    url = "https://github.com/bitcoin-core/secp256k1.git"
    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = {"shared": False, "fPIC": True}

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def layout(self):
        cmake_layout(self, src_folder="src")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)

    def generate(self):
        tc = CMakeToolchain(self)
        # Disable all tests and benchmarks.
        tc.variables["SECP256K1_INSTALL"] = True
        tc.variables["SECP256K1_BUILD_BENCHMARK"] = False
        tc.variables["SECP256K1_BUILD_TESTS"] = False
        tc.variables["SECP256K1_BUILD_EXHAUSTIVE_TESTS"] = False
        tc.variables["SECP256K1_BUILD_CTIME_TESTS"] = False
        tc.variables["SECP256K1_BUILD_EXAMPLES"] = False
        tc.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        cmake = CMake(self)
        cmake.install()

        # These headers are used by XRPLF/mpt-crypto which is why we need to package them.
        # ecmult_impl.h reads the library's own secp256k1_pre_g tables, so consumers must link the
        # static library and must not compile with an ECMULT_WINDOW_SIZE larger than the library's.
        src_headers = ["util.h", "int128_impl.h", "scalar_impl.h", "field_impl.h", "group_impl.h",
                       "ecmult_impl.h", "scratch_impl.h"]
        src_dir = os.path.join(self.source_folder, "src")
        for header in self._with_included_headers(src_dir, src_headers):
            copy(self, header, src=src_dir, dst=os.path.join(self.package_folder, "include", "private"))

    def _with_included_headers(self, src_dir, headers):
        # Follow `#include "..."` transitively, keeping only files inside src/ (this skips
        # "../include/secp256k1.h", which cmake.install() already provides).
        include_re = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
        found = set()
        pending = list(headers)
        while pending:
            header = pending.pop()
            if header in found:
                continue
            found.add(header)
            content = load(self, os.path.join(src_dir, header))
            for included in include_re.findall(content):
                if not os.path.normpath(included).startswith(".."):
                    pending.append(included)
        return sorted(found)

    def package_info(self):
        self.cpp_info.libs = ["secp256k1"]
        self.cpp_info.set_property("cmake_file_name", "secp256k1")
        self.cpp_info.set_property("cmake_target_name", "secp256k1::secp256k1")

        if self.settings.os == "Windows" and not self.options.shared:
            self.cpp_info.defines.append("SECP256K1_STATIC")
