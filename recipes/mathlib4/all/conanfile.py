import os
import shutil
from io import StringIO
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.build import build_jobs
from conan.tools.env import Environment
from conan.tools.files import copy

# 2.1: `quiet` on self.run.
required_conan_version = ">=2.1.0"


class Mathlib4Conan(ConanFile):
    """Prebuilt mathlib and its Lean dependency closure: the olean tree, so
    lake resolves imports without re-elaborating mathlib, and the native
    objects in one archive, lib/libmathlib4.a. The version is the Lean version
    of lean4/<version>, which builds it and whose runtime the objects call.

    The closure is pinned by lake/<version>/lake-manifest.json, packaged so
    consumers can check theirs matches.

    Building needs `git` and `curl` on PATH and network access.
    """

    name = "mathlib4"
    description = "Prebuilt Lean 4 mathlib and its dependency closure"
    # Cli is MIT; the rest of the closure is Apache-2.0.
    license = ("Apache-2.0", "MIT")
    url = "https://github.com/XRPLF/conan-center-index"
    homepage = "https://github.com/leanprover-community/mathlib4"
    topics = ("lean", "lean4", "mathlib", "formal-verification", "pre-built")

    package_type = "static-library"
    # Plain C objects and oleans: one package per platform.
    settings = "os", "arch"

    def export_sources(self):
        # The lake workspace; `lake exe cache get` also reads lean-toolchain.
        copy(self, "*", src=os.path.join(self.recipe_folder, "lake", self.version), dst=self.export_sources_folder)

    def package_id(self):
        # Profiles inject confs into every package_id.
        self.info.conf.clear()

    def validate(self):
        if self.settings.os == "Windows":
            raise ConanInvalidConfiguration(f"{self.ref}: Windows is not supported yet")

    def validate_build(self):
        # leanc compiles for the build platform, so a cross build would
        # package build-platform objects under the host package_id.
        if str(self.settings.os) != str(self.settings_build.os) or str(self.settings.arch) != str(
            self.settings_build.arch
        ):
            raise ConanInvalidConfiguration(f"{self.ref}: cross-building is not supported")

    def requirements(self):
        # Callers of the objects need lean.h.
        self.requires(f"lean4/{self.version}", transitive_headers=True)

    def build_requirements(self):
        self.tool_requires(f"lean4/{self.version}")

    def generate(self):
        env = Environment()
        # Either would change what lake builds with or keys its traces on.
        env.unset("LEAN_CC")
        env.unset("LEAN_GITHASH")
        env.define("LEAN_NUM_THREADS", str(build_jobs(self)))
        # Keep the cache tool's downloads (hundreds of MB) in the build folder.
        env.define_path("MATHLIB_CACHE_DIR", os.path.join(self.build_folder, "mathlib-cache"))
        env.vars(self).save_script("lean_env")

    def build(self):
        targets = " ".join(self.conan_data["dep_targets"][self.version])
        # lake prints tens of thousands of lines: only shown on failure.
        log = StringIO()
        try:
            self.run("lake exe cache get", stdout=log, stderr=log)
            self.run(f"lake build {targets}", stdout=log, stderr=log)
        except Exception:
            self.output.error(log.getvalue())
            raise
        self._bundle()

    def _bundle(self):
        # One archive for the whole closure, so consumers need no link order.
        # ir/Cache/ is mathlib's `cache` executable.
        objects = sorted(
            str(path)
            for path in Path(".lake", "packages").rglob("*.c.o.export")
            if "/ir/Cache/" not in path.as_posix()
        )
        if not objects:
            raise ConanException(f"{self.ref}: lake built no objects")
        # `q` appends to a leftover archive (local `conan build` re-runs).
        Path("libmathlib4.a").unlink(missing_ok=True)
        # ~8,000 paths overflow ARG_MAX, so they go in a list file (libtool on
        # macOS, whose ar takes none). ar tokenizes it like a shell: quote each
        # path, for Mathlib/Tactic/LinearCombination' and the like.
        if self.settings.os == "Macos":
            Path("objects.txt").write_text("".join(f"{path}\n" for path in objects))
            self.run("libtool -static -o libmathlib4.a -filelist objects.txt")
        else:
            Path("objects.rsp").write_text("".join(f'"{path}"\n' for path in objects))
            self.run("ar qcs libmathlib4.a @objects.rsp")

    def package(self):
        packages = os.path.join(self.package_folder, "packages")
        # The olean tree, without what the archive replaces or consumers never
        # use: objects, per-library archives, executables.
        copy(
            self,
            "*",
            src=os.path.join(self.build_folder, ".lake", "packages"),
            dst=packages,
            excludes=["*.c.o.export", "*.c.o.export.trace", "*.a", "*.a.trace", "*/.lake/build/bin/*"],
        )
        for repo in sorted(Path(packages).iterdir()):
            copy(self, "LICENSE*", src=repo, dst=os.path.join(self.package_folder, "licenses", repo.name))
            self._shallow_git(repo)
        copy(self, "libmathlib4.a", src=self.build_folder, dst=os.path.join(self.package_folder, "lib"))
        # The exported one: lake may rewrite the build folder's.
        copy(self, "lake-manifest.json", src=self.source_folder, dst=self.package_folder)

    def _shallow_git(self, repo):
        # lake reads each dependency's revision and URL from its `.git`, and
        # re-clones without one. Keep only the pinned commit: mathlib's history
        # is several hundred MB.
        def git(args):
            out = StringIO()
            self.run(f'git -C "{repo}" {args}', stdout=out, quiet=True)
            return out.getvalue().strip()

        rev = git("rev-parse HEAD")
        url = git("remote get-url origin")
        full = repo / ".git.full"
        (repo / ".git").rename(full)
        git("init -q")
        git(f'fetch -q --depth 1 "file://{full}" {rev}')
        git(f"update-ref HEAD {rev}")
        git("read-tree HEAD")
        git(f'remote add origin "{url}"')
        shutil.rmtree(full)

    def package_info(self):
        self.cpp_info.libs = ["mathlib4"]
        self.cpp_info.includedirs = []
        # The olean tree a consumer mounts as its .lake/packages, and the
        # manifest it checks its own pins against.
        self.cpp_info.set_property("lean4_packages_dir", os.path.join(self.package_folder, "packages"))
        self.cpp_info.set_property("lean4_lake_manifest", os.path.join(self.package_folder, "lake-manifest.json"))
