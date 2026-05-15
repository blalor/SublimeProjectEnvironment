#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_name="Project Environment"
sublime_packages="$HOME/Library/Application Support/Sublime Text/Packages"
package_dir="$sublime_packages/$package_name"

mkdir -p "$package_dir"
if [[ -L "$package_dir" ]]; then
  rm "$package_dir"
  mkdir -p "$package_dir"
fi
rm -f \
  "$package_dir/project_environment.py" \
  "$package_dir/Default.sublime-commands" \
  "$package_dir/Project Environment.sublime-settings" \
  "$package_dir/.python-version"
cp \
  "$repo_root/sublime-package/$package_name/project_environment.py" \
  "$repo_root/sublime-package/$package_name/Default.sublime-commands" \
  "$repo_root/sublime-package/$package_name/Project Environment.sublime-settings" \
  "$repo_root/sublime-package/$package_name/.python-version" \
  "$package_dir/"

printf 'Installed %s package files in:\n  %s\n' "$package_name" "$package_dir"
