#!/usr/bin/env bash
set -euo pipefail

if [[ "$(dpkg --print-architecture)" != amd64 ]]; then
  echo 'LLVM BOLT tools require an amd64 Linux runner' >&2
  exit 1
fi

case "$(jq -er '.release.upstream_rust_version' "$MANIFEST_PATH")" in
  1.97.* | 1.98.*)
    bolt_major=22
    bolt_version='22.1.8~++20260714014902+ca7933e47d3a-1~exp1~20260714135019.80'
    bolt_sha256='97a9e4e8d2b2219757c38abef93e913793ebc64580aa51207bd23941c44ec070'
    runtime_sha256='48639dafeb45892eec58f5d8a2d0d612ce791a2f713f06c794b71d6a72fa582d'
    ;;
  1.99.*)
    bolt_major=23
    bolt_version='23.1.2'
    bolt_sha256='b5ed9675149cc837c282e9b6962c276c9fa62863d5b2f91537b60848552995b7'
    ;;
  *)
    echo 'Pin matching LLVM BOLT tools for this Rust version' >&2
    exit 1
    ;;
esac
bolt_root="$(mktemp -d "${RUNNER_TEMP:?}/ohm-bolt.XXXXXX")"
if [[ "$bolt_major" == 23 ]]; then
  bolt_archive="$bolt_root/llvm.tar.xz"
  bolt_directory="LLVM-$bolt_version-Linux-X64"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
    --fail --location --retry 3 --show-error --silent \
    --output "$bolt_archive" \
    "https://github.com/llvm/llvm-project/releases/download/llvmorg-$bolt_version/$bolt_directory.tar.xz"
  printf '%s  %s\n' "$bolt_sha256" "$bolt_archive" | sha256sum --check --strict
  # Leave llvm-profdata for the build to link from Rust's matching LLVM.
  tar -xJf "$bolt_archive" -C "$bolt_root" --strip-components=1 --occurrence=1 \
    "$bolt_directory/bin/llvm-bolt" \
    "$bolt_directory/bin/merge-fdata" \
    "$bolt_directory/lib/libbolt_rt_hugify.a" \
    "$bolt_directory/lib/libbolt_rt_instr.a"
  rm "$bolt_archive"
  bolt_llvm_dir="$bolt_root"
else
  bolt_base_url="https://apt.llvm.org/noble/pool/main/l/llvm-toolchain-$bolt_major"
  for package in "bolt-$bolt_major" "libbolt-$bolt_major-dev"; do
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
      --fail --location --retry 3 --show-error --silent \
      --output "$bolt_root/$package.deb" \
      "$bolt_base_url/${package}_${bolt_version}_amd64.deb"
  done

  printf '%s  %s\n' \
    "$bolt_sha256" \
    "$bolt_root/bolt-$bolt_major.deb" \
    "$runtime_sha256" \
    "$bolt_root/libbolt-$bolt_major-dev.deb" \
    | sha256sum --check --strict

  dpkg-deb --extract "$bolt_root/bolt-$bolt_major.deb" "$bolt_root"
  dpkg-deb --extract "$bolt_root/libbolt-$bolt_major-dev.deb" "$bolt_root"
  bolt_llvm_dir="$bolt_root/usr/lib/llvm-$bolt_major"
fi
"$bolt_llvm_dir/bin/llvm-bolt" --version
"$bolt_llvm_dir/bin/merge-fdata" --version
if [[ ! -f "$bolt_llvm_dir/lib/libbolt_rt_instr.a" ]]; then
  echo 'LLVM BOLT instrumentation runtime is missing' >&2
  exit 1
fi

printf 'OHM_BOLT_LLVM_DIR=%s\n' "$bolt_llvm_dir" >> "$GITHUB_ENV"
