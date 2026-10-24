import glob
import os
import shutil
from io import StringIO

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.cmake import CMake, CMakeToolchain
from conan.tools.env import Environment
from conan.tools.gnu import PkgConfigDeps
from conan.tools.scm import Git

# 2.7: PkgConfigDeps.set_property.
required_conan_version = ">=2.7.0"

# The system loader, per arch, as in xrpld's bin/default-loader-path.sh.
LINUX_LOADERS = {
    "x86_64": "/lib64/ld-linux-x86-64.so.2",
    "armv8": "/lib/ld-linux-aarch64.so.1",
}


def _ci_builds_once(conanfile):
    # Every job of the CI matrix (gcc/clang x Debug/Release) computes the same
    # package id, and would build it in parallel. Only the Release job (gcc's on
    # Linux) does; in the others this is an invalid configuration, which CI
    # skips. The build profile carries build_type, which this recipe ignores.
    build = conanfile.settings_build
    if os.getenv("GITHUB_ACTIONS") == "true" and (
        build.get_safe("build_type") != "Release" or (build.os == "Linux" and build.compiler != "gcc")
    ):
        raise ConanInvalidConfiguration(f"{conanfile.ref}: built by the CI's Release (Linux: gcc) job only")


class Lean4Conan(ConanFile):
    """The Lean 4 toolchain (lean, lake, leanc, headers, runtime), built from
    the tagged release commit. Building from git sets the right git hash in
    order to reuse the build artifacts.

    Building needs git and network access: Lean's own CMake clones cadical,
    fetches mimalloc and downloads a prebuilt leantar.

    The binaries are relocatable like xrpld's: libstdc++ is linked statically
    and, on Linux, the interpreter and RUNPATH name nothing of the builder, so
    they run on any system with a glibc at least as new as the builder's."""

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
        # Relocatable and self-contained, so one binary per platform serves
        # every compiler and profile.
        del self.info.settings.compiler
        self.info.conf.clear()

    def validate(self):
        if self.settings.compiler == "msvc":
            raise ConanInvalidConfiguration(f"{self.ref}: MSVC is not supported")

    def validate_build(self):
        _ci_builds_once(self)

    def requirements(self):
        self.requires("gmp/6.3.0")
        self.requires("libuv/1.53.0")
        self.requires("openssl/[>=3 <4]")

    def build_requirements(self):
        self.tool_requires("cmake/[>=3.21 <5]")
        self.tool_requires("pkgconf/2.2.0")
        if self.settings.os == "Linux":
            self.tool_requires("patchelf/0.18")

    def source(self):
        source = self.conan_data["sources"][self.version]
        git = Git(self)
        git.clone(source["url"], target=".", args=["--depth=1", f"--branch=v{self.version}"])
        if git.get_commit() != source["commit"]:
            raise ConanException(f"v{self.version} is at {git.get_commit()}, expected {source['commit']}")

    def generate(self):
        # Lean's own build only works with Makefiles. Its root CMake configures
        # the two stages itself: stage 0 only receives typed CMAKE_* cache
        # entries, which Conan's untyped -DCMAKE_TOOLCHAIN_FILE is not, and
        # stage 1 receives it as the relative path Conan passes, which does not
        # resolve from its directory, so both get the absolute path.
        tc = CMakeToolchain(self, generator="Unix Makefiles")
        toolchain = os.path.join(self.generators_folder, "conan_toolchain.cmake")
        tc.cache_variables["STAGE0_CMAKE_TOOLCHAIN_FILE"] = toolchain
        tc.cache_variables["STAGE1_CMAKE_TOOLCHAIN_FILE"] = toolchain
        # The licences would be installed at the package root, where `LICENSES`
        # (a file) and `licenses/` collide on a case-insensitive filesystem.
        tc.cache_variables["INSTALL_LICENSE"] = False
        # Lean packages whatever cadical and leantar it finds on PATH (e.g. a
        # Nix lean4 with an older leantar that cannot read mathlib's cache)
        # before building/downloading its pinned ones. A false value skips that
        # search and takes the pinned branch.
        tc.cache_variables["CADICAL"] = False
        tc.cache_variables["LEANTAR"] = False
        compilers = self.conf.get("tools.build:compiler_executables", default={}, check_type=dict)
        # leanc is told to call the profile's C compiler by name, so it works
        # wherever that compiler is.
        tc.cache_variables["LEANC_CC"] = compilers.get("c", "cc")
        # Standalone mode keeps the dependencies' absolute paths out of the link
        # flags leanc and lake hand to user builds; they are named instead and
        # found through LIBRARY_PATH (set below for this build), as upstream's
        # releases do.
        tc.cache_variables["LEAN_STANDALONE"] = True
        libs = "-lgmp -luv -lssl -lcrypto"
        if any(dep.ref.name == "zlib" for dep in self.dependencies.host.values()):
            libs += " -lz"  # openssl built with zlib
        if self.settings.os == "Linux":
            libs = f"-Wl,--as-needed {libs} -lpthread -ldl -lrt -Wl,--no-as-needed"
        tc.cache_variables["LEAN_EXTRA_LINKER_FLAGS"] = libs
        if self.settings.os == "Linux" and str(self.settings.compiler.libcxx).startswith("libstdc++"):
            # Static libstdc++, as xrpld links it, kept out of the dynamic
            # symbol table since libleanshared is loaded next to the consumer's
            # own. g++ appends a -lstdc++ of its own, gcc does not.
            tc.cache_variables["LEAN_CXX_STDLIB"] = (
                "-static-libstdc++ -Wl,-Bstatic -lstdc++ -Wl,-Bdynamic -Wl,--exclude-libs,libstdc++.a"
            )
            # cadical is linked by a plain makefile with `c++`; this builds it
            # with the profile's compiler and these linker flags.
            tc.cache_variables["CADICAL_USE_CUSTOM_CXX"] = True
            tc.cache_variables["LEANC_INTERNAL_LINKER_FLAGS"] = "-static-libstdc++"
        tc.generate()
        # Lean finds gmp, libuv and openssl through pkg-config, by those names.
        deps = PkgConfigDeps(self)
        deps.set_property("libuv", "pkg_config_name", "libuv")
        deps.generate()
        env = Environment()
        for dep in self.dependencies.host.values():
            for libdir in dep.cpp_info.aggregated_components().libdirs:
                env.prepend_path("LIBRARY_PATH", libdir)
        env.vars(self, scope="build").save_script("lean_library_path")

    def build(self):
        # Without git at configure time Lean silently embeds an empty hash.
        if shutil.which("git") is None:
            raise ConanException(f"{self.ref}: git is needed on PATH to build")
        cmake = CMake(self)
        cmake.configure()
        cmake.build()
        expected = self.conan_data["sources"][self.version]["commit"]
        githash = StringIO()
        self.run(f'"{os.path.join(self.build_folder, "stage1", "bin", "lean")}" --githash', stdout=githash)
        if githash.getvalue().strip() != expected:
            raise ConanException(f"{self.ref}: built githash {githash.getvalue().strip()!r}, expected {expected}")

    def package(self):
        cmake = CMake(self)
        cmake.install()
        licenses = os.path.join(self.package_folder, "licenses")
        os.makedirs(licenses)
        for name in ("LICENSE", "LICENSES"):
            shutil.copy(os.path.join(self.source_folder, name), licenses)
        if self.settings.os == "Linux":
            self._relocate()

    def _patchelf(self, args, check=True):
        out = StringIO()
        try:
            self.run(f"patchelf {args}", stdout=out, stderr=StringIO(), quiet=True)
        except ConanException:
            if check:
                raise
        return out.getvalue().strip()

    def _relocate(self):
        # As xrpld's PatchNixBinary: a Nix toolchain links against its own
        # loader and adds its library directories to RUNPATH. Point the
        # interpreter at the system loader and keep only Lean's $ORIGIN entries.
        loader = LINUX_LOADERS[str(self.settings.arch)]
        files = glob.glob(os.path.join(self.package_folder, "bin", "*"))
        files += glob.glob(os.path.join(self.package_folder, "lib", "lean", "*.so"))
        for path in files:
            if os.path.islink(path):
                continue
            with open(path, "rb") as f:
                if f.read(4) != b"\x7fELF":
                    continue
            if self._patchelf(f'--print-interpreter "{path}"', check=False):
                self._patchelf(f'--set-interpreter {loader} "{path}"')
            rpath = self._patchelf(f'--print-rpath "{path}"', check=False).split(":")
            kept = [entry for entry in rpath if entry.startswith("$ORIGIN")]
            if kept != [entry for entry in rpath if entry]:
                self._patchelf(f"--set-rpath '{':'.join(kept)}' \"{path}\"")

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "lean4")
        self.cpp_info.set_property("cmake_target_name", "lean4::lean4")
        libdir = os.path.join("lib", "lean")
        leanshared = self.cpp_info.components["leanshared"]
        leanshared.set_property("cmake_target_name", "lean4::leanshared")
        leanshared.includedirs = ["include"]
        leanshared.libdirs = [libdir]
        leanshared.bindirs = ["bin"]
        leanshared.libs = ["leanshared"]
        leanshared.requires = ["gmp::gmp", "libuv::libuv", "openssl::ssl", "openssl::crypto"]
        lake = self.cpp_info.components["lake"]
        lake.set_property("cmake_target_name", "lean4::lake")
        lake.includedirs = []
        lake.libdirs = [libdir]
        lake.bindirs = []
        lake.libs = ["Lake"]
        lake.requires = ["leanshared"]
