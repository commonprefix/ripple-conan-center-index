import os
import shutil
from io import StringIO

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.cmake import CMake, CMakeToolchain
from conan.tools.gnu import PkgConfigDeps
from conan.tools.scm import Git

# 2.7: PkgConfigDeps.set_property.
required_conan_version = ">=2.7.0"


class Lean4Conan(ConanFile):
    """The Lean 4 toolchain (lean, lake, leanc, headers, runtime), built from
    the release commit so that its githash, which lake keys its traces on,
    matches mathlib's olean cache.

    Building needs git and network access (cadical, mimalloc, leantar)."""

    name = "lean4"
    description = "The Lean 4 theorem prover and toolchain"
    license = "Apache-2.0"
    url = "https://github.com/XRPLF/conan-center-index"
    homepage = "https://github.com/leanprover/lean4"
    topics = ("lean", "lean4", "theorem-prover", "formal-verification")

    # No build_type: Lean builds Release by default, which is what consumers
    # want whatever their own build type.
    settings = "os", "arch", "compiler"

    def layout(self):
        # Not cmake_layout, which needs build_type.
        self.folders.source = "src"
        self.folders.build = "build"
        self.folders.generators = os.path.join("build", "generators")

    def configure(self):
        self.settings.rm_safe("compiler.cppstd")

    def package_id(self):
        # One binary per platform for the Nix dev shell, whatever the
        # consumer's compiler or profile.
        del self.info.settings.compiler
        self.info.conf.clear()

    def validate(self):
        if self.settings.compiler == "msvc":
            raise ConanInvalidConfiguration(f"{self.ref}: MSVC is not supported")

    def requirements(self):
        self.requires("gmp/6.3.0")
        self.requires("libuv/1.53.0")
        self.requires("openssl/[>=3 <4]")

    def build_requirements(self):
        self.tool_requires("cmake/[>=3.21 <5]")
        self.tool_requires("pkgconf/2.2.0")

    def source(self):
        source = self.conan_data["sources"][self.version]
        Git(self).fetch_commit(source["url"], source["commit"])

    def generate(self):
        # Lean only builds with Makefiles, and configures its two stages as
        # sub-builds that do not get Conan's toolchain file: pass its path.
        tc = CMakeToolchain(self, generator="Unix Makefiles")
        toolchain = os.path.join(self.generators_folder, "conan_toolchain.cmake")
        tc.cache_variables["STAGE0_CMAKE_TOOLCHAIN_FILE"] = toolchain
        tc.cache_variables["STAGE1_CMAKE_TOOLCHAIN_FILE"] = toolchain
        # Installed at the root, `LICENSES` (a file) would collide with
        # `licenses/` on a case-insensitive filesystem; package() copies them.
        tc.cache_variables["INSTALL_LICENSE"] = False
        # Use the pinned cadical and leantar, not whatever is on PATH (the Nix
        # shell's lean4 has an older leantar that cannot read mathlib's cache).
        tc.cache_variables["CADICAL"] = False
        tc.cache_variables["LEANTAR"] = False
        # Keep the binaries working in later Nix dev shells, where only the
        # pinned glibc stays at the same store path: leanc calls the C compiler
        # by name, and libstdc++ is static and kept out of the dynamic symbol
        # table, since libleanshared is loaded next to the consumer's own.
        compilers = self.conf.get("tools.build:compiler_executables", default={}, check_type=dict)
        tc.cache_variables["LEANC_CC"] = compilers.get("c", "cc")
        if self.settings.os == "Linux" and str(self.settings.compiler.libcxx).startswith("libstdc++"):
            tc.cache_variables["LEAN_CXX_STDLIB"] = (
                "-static-libstdc++ -Wl,-Bstatic -lstdc++ -Wl,-Bdynamic -Wl,--exclude-libs,libstdc++.a"
            )
            # cadical's makefile links with `c++` unless told otherwise.
            tc.cache_variables["CADICAL_USE_CUSTOM_CXX"] = True
            tc.cache_variables["LEANC_INTERNAL_LINKER_FLAGS"] = "-static-libstdc++"
        tc.generate()
        # Lean finds gmp, libuv and openssl through pkg-config, by those names.
        deps = PkgConfigDeps(self)
        deps.set_property("libuv", "pkg_config_name", "libuv")
        deps.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()
        # Without git at configure time Lean silently embeds an empty githash.
        expected = self.conan_data["sources"][self.version]["commit"]
        githash = StringIO()
        self.run(f'"{os.path.join(self.build_folder, "stage1", "bin", "lean")}" --githash', stdout=githash)
        if githash.getvalue().strip() != expected:
            raise ConanException(f"{self.ref}: built githash {githash.getvalue().strip()!r}, expected {expected}")

    def package(self):
        CMake(self).install()
        licenses = os.path.join(self.package_folder, "licenses")
        os.makedirs(licenses)
        for name in ("LICENSE", "LICENSES"):
            shutil.copy(os.path.join(self.source_folder, name), licenses)

    def package_info(self):
        self.cpp_info.libdirs = [os.path.join("lib", "lean")]
        # Lake before the runtime it depends on.
        self.cpp_info.libs = ["Lake", "leanshared"]
