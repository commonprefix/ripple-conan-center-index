import os

from conan import ConanFile
from conan.tools.build import can_run
from conan.tools.cmake import CMake, cmake_layout


class TestPackageConan(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    generators = "CMakeToolchain", "CMakeDeps", "VirtualRunEnv"
    test_type = "explicit"

    def layout(self):
        cmake_layout(self)

    def requirements(self):
        self.requires(self.tested_reference_str)

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def test(self):
        if can_run(self):
            # The toolchain itself, by its package path: a lean/lake found on
            # PATH (an elan proxy, say) would not test this package.
            bindir = self.dependencies["lean4"].cpp_info.bindirs[0]
            for tool in ("lean", "lake"):
                self.run(f'"{os.path.join(bindir, tool)}" --version', env="conanrun")
            for name in ("test_package", "test_leanshared"):
                bin_path = os.path.join(self.cpp.build.bindirs[0], name)
                self.run(bin_path, env="conanrun")
