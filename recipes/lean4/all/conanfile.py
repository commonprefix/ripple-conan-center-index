import os

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import copy, get
from conan.tools.layout import basic_layout

required_conan_version = ">=2.0.0"


class Lean4Conan(ConanFile):
    """The Lean 4 toolchain (lean, lake, leanc, headers, runtime).

    Unpacks the official leanprover/lean4 release rather than building from
    source. A release build reports the upstream `lean --githash`, which lake
    records in its build traces, so artifacts produced with it stay compatible
    with the mathlib olean cache.

    No package_type is declared: the release is at once a toolchain (bin/lean,
    bin/lake) and a mix of static and shared libraries (libLake.a beside
    libleanshared.so), with no shared/static choice to expose. Declaring
    "library" would require a `shared` option that means nothing here.
    """

    name = "lean4"
    description = "The Lean 4 theorem prover and toolchain"
    license = "Apache-2.0"
    url = "https://github.com/XRPLF/conan-center-index"
    homepage = "https://github.com/leanprover/lean4"
    topics = ("lean", "lean4", "theorem-prover", "formal-verification", "pre-built")

    # The release archives are prebuilt, so their contents depend only on the
    # platform, not on the consumer's compiler or build type. Declaring os/arch
    # alone yields exactly one binary per platform, shared by every consumer
    # configuration, instead of an identical copy per compiler/build_type.
    settings = "os", "arch"

    @property
    def _releases(self):
        return self.conan_data["sources"][self.version]

    def layout(self):
        basic_layout(self, src_folder="src")

    def package_id(self):
        # An unpacked upstream release: the content depends on the platform and
        # nothing else. Consumer profiles inject C++ concerns into every
        # package_id through `tools.info.package_id:confs` (rippled's default
        # profile adds user.package:cppstd_version, XRPLF's ci profile also
        # user.package:libc_version); clearing them keeps
        # one binary per platform, so a consumer whose profile differs from the
        # publisher's still gets a cache hit instead of re-downloading.
        self.info.conf.clear()

    def validate(self):
        # No release listed in conandata.yml => ConanInvalidConfiguration.
        # This specific error is then interpreted as "skip this combination" by the CI
        os_name, arch = str(self.settings.os), str(self.settings.arch)
        if arch not in self._releases.get(os_name, {}):
            raise ConanInvalidConfiguration(
                f"{self.name}/{self.version}: no upstream release for "
                f"{os_name}/{arch}"
            )

    @property
    def _release_folder(self):
        # A subfolder, so the layout's generators folder stays out of package().
        return os.path.join(self.build_folder, "release")

    # Downloaded in build() into the build folder: the archive is
    # platform-specific, while source() and the source folder are shared across
    # package_ids, so a second platform would unpack over the first.
    def build(self):
        get(
            self,
            **self._releases[str(self.settings.os)][str(self.settings.arch)],
            destination=self._release_folder,
            strip_root=True,
            keep_permissions=True,
        )

    def package(self):
        # Keep the release layout as shipped: bin/ needs lib/lean/ beside it,
        # and lake resolves the stdlib relative to its own location. The two
        # licence files (LICENSES is a file, the third-party notices) move to
        # licenses/ and are left out of the root: on a case-insensitive
        # filesystem `LICENSES` and `licenses/` are the same path, and
        # creating the directory next to the file fails on macOS.
        copy(
            self,
            "*",
            src=self._release_folder,
            dst=self.package_folder,
            excludes=["LICENSE", "LICENSES"],
        )
        for name in ("LICENSE", "LICENSES"):
            copy(
                self,
                name,
                src=self._release_folder,
                dst=os.path.join(self.package_folder, "licenses"),
            )

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "lean4")
        self.cpp_info.set_property("cmake_target_name", "lean4::lean4")
        libdir = os.path.join("lib", "lean")
        # Two components, so a consumer that only needs the runtime can link
        # lean4::leanshared and skip libLake. lean4::lean4 carries both.
        # Conan puts bindirs on PATH for tool_requires consumers by itself, so
        # no explicit buildenv_info is needed.
        leanshared = self.cpp_info.components["leanshared"]
        leanshared.set_property("cmake_target_name", "lean4::leanshared")
        leanshared.includedirs = ["include"]
        leanshared.libdirs = [libdir]
        leanshared.bindirs = ["bin"]
        leanshared.libs = ["leanshared"]
        lake = self.cpp_info.components["lake"]
        lake.set_property("cmake_target_name", "lean4::lake")
        lake.includedirs = []
        lake.libdirs = [libdir]
        lake.bindirs = []
        lake.libs = ["Lake"]
        # Lake depends on the runtime; the requires keeps the link order.
        lake.requires = ["leanshared"]
