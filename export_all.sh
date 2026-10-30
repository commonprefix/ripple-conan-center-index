#!/usr/bin/env bash

set -ex

if ! command -v yq &> /dev/null; then
    echo "yq could not be found. Please install yq to run this script."
    exit 1
fi

DIRECTORY=$(dirname "$0")

pushd "${DIRECTORY}"

for reference in $(yq '.recipes[]' recipes.yml); do
    name="${reference%%/*}"
    version="${reference#*/}"

    folder=$(yq --exit-status ".versions.\"${version}\".folder" "recipes/${name}/config.yml")
    directory="recipes/${name}/${folder}"

    # Check the version is available in conandata.yml
    yq --exit-status ".sources | has(\"${version}\")" "${directory}/conandata.yml"
    conan export "${directory}" --version="${version}"
done

popd
