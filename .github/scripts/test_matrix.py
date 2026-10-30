"""Print the inputs of .github/workflows/export.yml as GitHub step outputs."""

import argparse
import json
import subprocess
from pathlib import Path

import yaml

# xrpl-rpc-spec's test_package is written for Clio.
OPTION_OVERRIDES = {"xrpl-rpc-spec/*:server": "clio"}

# Changing these tests all the recipes.
CI_FILES = {".github/workflows/export.yml", ".github/scripts/test_matrix.py"}


def run(*command: str) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def list_recipes(recipes_yml: str) -> list[dict[str, str]]:
    recipes = []
    for reference in yaml.safe_load(recipes_yml)["recipes"]:
        name, version = reference.split("/")
        config = yaml.safe_load(Path("recipes", name, "config.yml").read_text())
        folder = config["versions"][version]["folder"]
        recipes.append({"reference": reference, "directory": f"recipes/{name}/{folder}", "version": version})
    return recipes


def changed_recipes(recipes: list[dict[str, str]], base: str) -> list[dict[str, str]]:
    """The recipes changed since `base`, or all of them if that can't be determined."""
    if not base:
        return recipes
    try:
        if subprocess.run(["git", "cat-file", "-e", f"{base}^{{commit}}"], capture_output=True).returncode != 0:
            run("git", "fetch", "--depth=1", "origin", base)
        changed_files = run("git", "diff", "--name-only", base, "HEAD").splitlines()
    except subprocess.CalledProcessError:
        return recipes
    if CI_FILES.intersection(changed_files):
        return recipes

    old_references = set(yaml.safe_load(run("git", "show", f"{base}:recipes.yml"))["recipes"])
    return [
        recipe
        for recipe in recipes
        if recipe["reference"] not in old_references
        or any(path.startswith(recipe["directory"] + "/") for path in changed_files)
    ]


def to_pairs(recipes: list[dict[str, str]]) -> str:
    """As "<directory>:<version>" pairs, as the test runners may not have Python with PyYAML, yq or jq."""
    return " ".join(f"{recipe['directory']}:{recipe['version']}" for recipe in recipes)


def xrpld_options(xrpld: Path) -> list[str]:
    inspect = json.loads(run("conan", "inspect", str(xrpld / "conanfile.py"), "--format=json"))
    options = {key: value for key, value in inspect["default_options"].items() if "/" in key}
    options.update(OPTION_OVERRIDES)
    return [f"{key}={value}" for key, value in options.items()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xrpld", type=Path, help="the xrpld checkout")
    parser.add_argument("--base", default="", help="only test the recipes changed since this commit")
    args = parser.parse_args()

    recipes = list_recipes(Path("recipes.yml").read_text())
    linux = json.loads((args.xrpld / ".github/scripts/strategy-matrix/linux.json").read_text())

    outputs = {
        "tests": to_pairs(changed_recipes(recipes, args.base)),
        # All of them, so that dependencies (e.g. grpc's abseil) resolve to the local recipes.
        "exports": to_pairs(recipes),
        "options": " ".join(xrpld_options(args.xrpld)),
        # So that all the test jobs use the same commit, even if develop moves on.
        "xrpld_sha": run("git", "-C", str(args.xrpld), "rev-parse", "HEAD").strip(),
        "linux_image": f"ghcr.io/xrplf/xrpld/nix-ubuntu:{linux['image_tag']}",
    }
    for key, value in outputs.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
