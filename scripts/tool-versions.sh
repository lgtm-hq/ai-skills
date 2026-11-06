#!/usr/bin/env bash
# Shared installer pins. Sourcing this file only assigns variables.
# Refresh versions and reviewed installer hashes together; see CONTRIBUTING.md.

# renovate: datasource=github-releases depName=astral-sh/uv
UV_VERSION="0.13.7"
# Checksum consumed by scripts sourcing this file.
# shellcheck disable=SC2034
UV_INSTALLER_SHA256="d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4"
# URL consumed by scripts sourcing this file.
# shellcheck disable=SC2034
UV_INSTALLER_URL="https://astral.sh/uv/${UV_VERSION}/install.sh"

# renovate: datasource=github-releases depName=oven-sh/bun extractVersion=^bun-v(?<version>.+)$
BUN_VERSION="1.4.4"
# Checksum consumed by scripts sourcing this file.
# shellcheck disable=SC2034
BUN_INSTALLER_SHA256="04882bf41679d49d9af108657a1e5515bf04fdf2940d12c0d0b1e5d79dc53be8"
# URL consumed by scripts sourcing this file.
# shellcheck disable=SC2034
BUN_INSTALLER_URL="https://raw.githubusercontent.com/oven-sh/bun/bun-v${BUN_VERSION}/src/runtime/cli/install.sh"
