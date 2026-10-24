import json
import os
import shutil
from io import StringIO
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.build import build_jobs
from conan.tools.env import Environment
from conan.tools.files import copy

# 2.1: `stderr` on self.run.
required_conan_version = ">=2.1.0"

PACKAGES_DIR = "packages"
LIB_DIR = "lib"
# Keep in step with cpp_info.libs in package_info: the linker derives the file
# name from the library name, so "mathlib4" there means "libmathlib4.a" here.
ARCHIVE_NAME = "libmathlib4.a"


class Mathlib4Conan(ConanFile):
    """Prebuilt mathlib and its Lean dependency closure: the olean tree, so
    lake can resolve imports without re-elaborating mathlib, and the native
    objects in one archive, lib/libmathlib4.a. The version is the Lean
    version; lean4/<version> builds it and is a host requirement, since the
    objects reference the Lean runtime.

    The pinned closure is lake/<version>/lake-manifest.json, exported with the
    recipe and packaged so consumers can check theirs matches; only the
    `packages` entries have to agree. The `:static` targets to build are in
    conandata.yml (`dep_targets`).

    Each dependency keeps a shallow `.git`: without one lake treats the URL
    as changed, deletes the directory and re-clones. Its index is packaged
    without stat data, so the first `git diff HEAD` on a consumer refreshes
    it in place, after which `conan cache check-integrity` reports the
    package as modified. Harmless for the build.

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
    # The objects are plain C compiled by whatever leanc calls on the builder,
    # linkable from any compiler and standard library; the oleans are
    # platform-only too. One package per platform, by choice.
    settings = "os", "arch"

    @property
    def _dep_targets(self):
        return self.conan_data["dep_targets"][self.version]

    def export_sources(self):
        # The lake workspace for this version. lean-toolchain is needed too:
        # `lake exe cache get` reads it.
        workspace = os.path.join(self.recipe_folder, "lake", self.version)
        for name in ("lakefile.toml", "lake-manifest.json", "lean-toolchain"):
            if not os.path.isfile(os.path.join(workspace, name)):
                raise ConanException(
                    f"{self.name}/{self.version}: missing {name} in "
                    f"lake/{self.version}/; each version needs its own lake "
                    f"workspace there"
                )
        copy(self, "*", src=workspace, dst=self.export_sources_folder)

    def package_id(self):
        # Consumer profiles inject confs into every package_id (rippled's
        # default profile user.package:cppstd_version, XRPLF's ci profile also
        # user.package:libc_version). Clearing them keeps one binary per
        # platform; a consumer on an older glibc than the builder's fails to
        # link, as with any prebuilt object.
        self.info.conf.clear()

    def validate(self):
        if self.settings.os == "Windows":
            raise ConanInvalidConfiguration(
                f"{self.name}/{self.version}: Windows is not supported yet"
            )

    def validate_build(self):
        # The tool_requires lean4 is the build platform's and leanc compiles
        # for it, so the objects would be build-platform code under the host
        # package_id. validate_build rather than validate: consumers can still
        # download correctly built host binaries.
        if (
            str(self.settings.os) != str(self.settings_build.os)
            or str(self.settings.arch) != str(self.settings_build.arch)
        ):
            raise ConanInvalidConfiguration(
                f"{self.name}/{self.version}: cross-building is not supported"
            )
        # Every job of the CI matrix (gcc/clang x Debug/Release) computes the
        # same package id, and would build it in parallel. Only the Release job
        # (gcc's on Linux) does, as for lean4; CI skips the others.
        build = self.settings_build
        if os.getenv("GITHUB_ACTIONS") == "true" and (
            build.get_safe("build_type") != "Release"
            or (build.os == "Linux" and build.compiler != "gcc")
        ):
            raise ConanInvalidConfiguration(
                f"{self.name}/{self.version}: built by the CI's Release (Linux: gcc) job only"
            )

    def requirements(self):
        # transitive_headers: anything that calls into the bundled objects
        # needs lean.h for the runtime it talks to.
        self.requires(f"lean4/{self.version}", transitive_headers=True)

    def build_requirements(self):
        self.tool_requires(f"lean4/{self.version}")

    def _require_tools(self):
        missing = [tool for tool in ("git", "curl") if shutil.which(tool) is None]
        if missing:
            raise ConanException(
                f"{self.name}/{self.version}: {' and '.join(missing)} not found "
                f"on PATH. lake clones the dependencies with git and mathlib's "
                f"cache tool downloads with curl."
            )

    def generate(self):
        env = Environment()
        env.unset("LEAN_CC")  # an ambient value would change the compiler behind leanc
        # LEAN_GITHASH would override the hash lake
        # keys its traces on (dev shells set it for other Lean builds).
        env.unset("LEAN_GITHASH")
        env.define("LEAN_NUM_THREADS", str(build_jobs(self)))
        # mathlib's cache tool keeps its downloads (hundreds of MB of .ltar) in
        # a per-user directory by default; under the build folder they go away
        # with it instead of piling up on a builder.
        env.define_path("MATHLIB_CACHE_DIR", os.path.join(self.build_folder, "mathlib-cache"))
        # lake links mathlib's cache tool with lean4's link flags, which name
        # gmp, libuv, openssl and zlib rather than give their paths.
        for dep in self.dependencies.host.values():
            for libdir in dep.cpp_info.aggregated_components().libdirs:
                env.prepend_path("LIBRARY_PATH", libdir)
        env.vars(self).save_script("lean_env")

    def build(self):
        self._require_tools()
        # Capture lake's output and surface it only on failure: a successful run
        # emits tens of thousands of progress lines.
        log = StringIO()
        try:
            for command in ("exe cache get", "build " + " ".join(self._dep_targets)):
                self.run(f"lake {command}", cwd=self.build_folder, stdout=log, stderr=log)
            objects = self._objects()
            self._bundle_deps(objects)
        except Exception:
            self.output.error(log.getvalue())
            raise
        self.output.info(
            f"{self.name}: compiled {len(objects)} objects into {ARCHIVE_NAME}"
        )

    def _objects(self):
        """Every `.c.o.export` under the dependency tree, sorted by relative
        path so the archive is byte-for-byte the same on every builder. Every
        generated `.c` must have one: lake's exit status already covers the
        targets it built, this covers objects and sources disagreeing in any
        other way. ir/Cache/ belongs to mathlib's own `cache` executable, the
        tool `lake exe cache get` runs, not library code."""
        packages_dir = Path(self.build_folder) / ".lake" / PACKAGES_DIR
        relative = lambda path: path.relative_to(packages_dir).as_posix()
        sources = {
            relative(path)[: -len(".c")]
            for path in packages_dir.rglob("*.c")
            if "/.lake/build/ir/" in relative(path) and "/ir/Cache/" not in relative(path)
        }
        objects = {
            relative(path)[: -len(".c.o.export")]: path
            for path in packages_dir.rglob("*.c.o.export")
            if "/ir/Cache/" not in relative(path)
        }
        if not objects:
            raise ConanException(f"{self.name}: lake built no objects under {packages_dir}")
        missing = sorted(sources - objects.keys())
        if missing:
            raise ConanException(
                f"{self.name}: {len(missing)} of {len(sources)} generated C sources have "
                f"no object: " + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
            )
        return [objects[key] for key in sorted(objects)]

    def _bundle_deps(self, objects):
        # ~8,000 paths overflow ARG_MAX, so they go in a list file. macOS's ar
        # reads no response file; libtool takes a plain list, as lake itself
        # does there. ar's @file is tokenized like a shell, so each path is
        # quoted and escaped as lake does: an unquoted apostrophe (as in
        # Mathlib/Tactic/LinearCombination') would swallow the following lines.
        # Members are stored by basename, so the archive holds many members of
        # the same name (one Basic.c.o.export per directory). That is
        # intentional: ar and the linker resolve by symbol, only extraction by
        # name (`ar x`) would overwrite.
        build_dir = Path(self.build_folder)
        archive = build_dir / ARCHIVE_NAME
        list_file = build_dir / "lean_deps_objects.rsp"
        if self.settings.os == "Macos":
            list_file.write_text("".join(f"{path}\n" for path in objects), encoding="utf-8")
            command = f'libtool -static -o "{archive}" -filelist "{list_file}"'
        else:
            list_file.write_text(
                "".join(
                    '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"\n'
                    for path in objects
                ),
                encoding="utf-8",
            )
            command = f'ar qcs "{archive}" "@{list_file}"'
        # `q` appends: a leftover archive (local `conan build` re-runs) would
        # keep its stale members.
        if archive.exists():
            archive.unlink()
        self.run(command)

    def package(self):
        build_dir = Path(self.build_folder)
        package_dir = Path(self.package_folder)
        # The lake build tree, so lake can resolve the model's imports without
        # re-elaborating mathlib. Excluded, as a model build never reads them:
        # the .c.o.export objects (bundled into the archive), each dependency's
        # own static library, and executables such as mathlib's `cache`. The
        # object traces go with the objects, and the `setup.json` files are
        # only read while compiling the module they belong to; both embed
        # build-folder paths and would make every build a new package
        # revision. The .c sources must stay: lake treats a module without
        # one as stale.
        copy(
            self,
            "*",
            src=build_dir / ".lake" / PACKAGES_DIR,
            dst=package_dir / PACKAGES_DIR,
            excludes=[
                "*.c.o.export",
                "*.c.o.export.trace",
                "*.setup.json",
                "*.a",
                "*.a.trace",
                "*.a.rsp",
                "*/.lake/build/bin/*",
            ],
        )
        packages_dir = package_dir / PACKAGES_DIR
        self._normalize_traces(packages_dir)
        self._shallow_git_repos(packages_dir)
        copy(self, ARCHIVE_NAME, src=build_dir, dst=package_dir / LIB_DIR)
        # From the source folder, Conan's untouched copy of the exported
        # workspace: lake may rewrite the build folder's manifest.
        copy(self, "lake-manifest.json", src=self.source_folder, dst=package_dir)
        self._package_licenses(build_dir, package_dir)

    def _package_licenses(self, build_dir, package_dir):
        # One directory per bundled project, named as in the manifest.
        manifest = json.loads(
            (Path(self.source_folder) / "lake-manifest.json").read_text(encoding="utf-8")
        )
        for entry in manifest["packages"]:
            name = entry["name"]
            copied = copy(
                self,
                "LICENSE*",
                src=build_dir / ".lake" / PACKAGES_DIR / name,
                dst=package_dir / "licenses" / name,
            )
            if not copied:
                raise ConanException(f"{self.name}: no LICENSE file in dependency {name}")

    def _normalize_traces(self, packages_dir):
        # Module traces lake wrote here (as opposed to the ones mathlib's cache
        # ships) also carry the build log and the input paths, which name the
        # build folder. Lake only decides on `depHash` and `outputs`, and reads
        # the rest as optional, so keep exactly what the cache's traces have.
        # Only lake's own output: ProofWidgets commits .trace files of its own
        # in its source tree, and those must stay as checked in.
        keep = ("schemaVersion", "depHash", "outputs")
        rewritten = 0
        for trace in packages_dir.rglob("*.trace"):
            if "/.lake/build/" not in trace.as_posix():
                continue
            data = json.loads(trace.read_text(encoding="utf-8"))
            if isinstance(data, dict) and set(data) - set(keep):
                trace.write_text(
                    json.dumps({key: data[key] for key in keep if key in data}), encoding="utf-8"
                )
                rewritten += 1
        self.output.info(f"{self.name}: trimmed {rewritten} module traces to depHash and outputs")

    def _git(self, repo, args, capture=False):
        out = StringIO() if capture else None
        self.run(f'git -C "{repo}" {args}', stdout=out, quiet=capture)
        return out.getvalue().strip() if capture else None

    def _shallow_git_repos(self, packages_dir):
        template = packages_dir.parent / "git-template"
        template.mkdir(exist_ok=True)
        for git_dir in sorted(packages_dir.glob("*/.git")):
            repo = git_dir.parent
            rev = self._git(repo, "rev-parse HEAD", capture=True)
            url = self._git(repo, "remote get-url origin", capture=True)
            full = git_dir.with_name(".git.full")
            git_dir.rename(full)
            self._git(repo, f'init -q --template="{template}"')
            self._git(
                repo,
                f'fetch -q --depth 1 "file://{full}" {rev}',
            )
            self._git(repo, f"-c core.logAllRefUpdates=false update-ref HEAD {rev}")
            self._git(repo, "read-tree HEAD")
            self._git(repo, f'remote add origin "{url}"')
            # The fetched pack reuses deltas from whatever pack the clone came
            # with; a single-threaded repack from scratch is the same bytes on
            # every builder.
            self._git(repo, "-c pack.threads=1 repack -a -d -f -q")
            shutil.rmtree(full)
            (git_dir / "FETCH_HEAD").unlink(missing_ok=True)
        template.rmdir()

    def package_info(self):
        package_dir = Path(self.package_folder)
        # libmathlib4.a rides the ordinary CMake target, so consumers link
        # mathlib4::mathlib4 rather than being handed a path.
        self.cpp_info.libs = ["mathlib4"]
        self.cpp_info.libdirs = [LIB_DIR]
        self.cpp_info.includedirs = []
        # Two things have no cpp_info equivalent, so they travel as properties:
        # the olean tree, which cmake/XrplLean4.cmake symlinks in as the model's
        # .lake/packages, and the manifest this package was built against, which
        # the consumer checks its own pin against before trusting those oleans.
        self.cpp_info.set_property("lean4_packages_dir", str(package_dir / PACKAGES_DIR))
        self.cpp_info.set_property(
            "lean4_lake_manifest", str(package_dir / "lake-manifest.json")
        )
