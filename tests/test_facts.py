"""Code-side extraction: flags, environment reads, project metadata."""

from docsdrift.facts import extract_file, is_support_path, norm_flag, scan_project
from docsdrift.repo import Repo


def flags(ff):
    return {f.name: f for f in ff.facts if f.kind == "flag"}


def envs(ff):
    return {f.name: f for f in ff.facts if f.kind == "env"}


def test_norm_flag():
    assert norm_flag("--Dry_Run") == "dry-run"
    assert norm_flag("output-dir") == "output-dir"


def test_argparse_flags_with_defaults_and_lines():
    src = (
        "import argparse\n"
        "TIMEOUT = 30\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--output-dir', default='./out')\n"
        "p.add_argument('-t', '--timeout', type=int, default=TIMEOUT)\n"
        "p.add_argument('--dry-run', action='store_true')\n"
    )
    got = flags(extract_file("app/cli.py", src))
    assert set(got) == {"--output-dir", "--timeout", "--dry-run"}
    assert (got["--output-dir"].line, got["--output-dir"].default, got["--output-dir"].has_default) == (4, "./out", True)
    assert got["--timeout"].default == 30          # resolved through the module constant
    assert got["--timeout"].line == 5


def test_click_option():
    src = (
        "import click\n\n"
        "@click.command()\n"
        "@click.option('--count', default=3, help='n')\n"
        "@click.option('--shout/--no-shout', default=False)\n"
        "def main(count, shout):\n    pass\n"
    )
    got = flags(extract_file("app/cli.py", src))
    assert got["--count"].default == 3
    assert "--shout" in got


def test_python_with_a_syntax_error_does_not_raise():
    ff = extract_file("app/broken.py", "def (:\n  add_argument('--x'\n")
    assert "x" in ff.flag_literals            # the literal trace still works


def test_env_reads_python():
    src = (
        "import os\n"
        "a = os.environ.get('APP_PORT', '8080')\n"
        "b = os.getenv('APP_HOST')\n"
        "c = os.environ['APP_KEY']\n"
    )
    got = envs(extract_file("app/settings.py", src))
    assert set(got) == {"APP_PORT", "APP_HOST", "APP_KEY"}
    assert (got["APP_PORT"].default, got["APP_PORT"].has_default, got["APP_PORT"].line) == ("8080", True, 2)
    assert got["APP_HOST"].has_default is False


def test_env_reads_javascript_and_go():
    js = "const port = process.env.APP_PORT || '3000'\nconst k = process.env['APP_KEY']\nconst m = import.meta.env.VITE_MODE\n"
    got = envs(extract_file("src/config.ts", js))
    assert got["APP_PORT"].default == "3000"
    assert {"APP_KEY", "VITE_MODE"} <= set(got)
    go = 'package main\nimport "os"\nfunc main() { _ = os.Getenv("APP_TOKEN") }\n'
    assert "APP_TOKEN" in envs(extract_file("main.go", go))


def test_env_tokens_are_a_loose_trace():
    ff = extract_file("deploy/run.sh", "export APP_REGION=eu\necho $APP_REGION\n")
    assert "APP_REGION" in ff.env_tokens
    assert envs(ff) == {}                      # not a structured read


def test_commander_and_yargs_options():
    js = (
        "program\n"
        "  .option('-p, --port <number>', 'port', '3000')\n"
        "  .option('--no-color', 'plain output')\n"
        "yargs.option('retries', { type: 'number', default: 2 })\n"
    )
    ff = extract_file("src/cli.js", js)
    got = flags(ff)
    assert got["--port"].default in ("3000", 3000)
    assert got["--retries"].default == 2
    assert "no-color" in ff.flag_literals and "--no-color" not in got


def test_go_pflag_definition_without_dashes():
    go = (
        "package cmd\n"
        "func init() {\n"
        '\trootCmd.Flags().StringP("output", "o", "dist", "output folder")\n'
        '\trootCmd.Flags().Bool("verbose", false, "more logs")\n'
        "}\n"
    )
    got = flags(extract_file("cmd/root.go", go))
    assert got["--output"].default == "dist" and got["--output"].line == 3
    assert got["--verbose"].default is False


def test_css_files_do_not_define_flags():
    ff = extract_file("site/style.css", ":root { --main-color: red; }\n")
    assert ff.flag_literals == set()


def test_support_paths():
    assert is_support_path("tests/test_cli.py")
    assert is_support_path("pkg/thing_test.go")
    assert is_support_path(".github/workflows/ci.yml")
    assert not is_support_path("src/app/cli.py")


def test_project_metadata(make_repo):
    root = make_repo({
        "pyproject.toml": '[project]\nname = "acme-tool"\n\n[project.scripts]\nacme = "acme.cli:main"\n',
        "acme/__init__.py": "",
        "package.json": '{"name": "@acme/web", "bin": {"acme-web": "bin.js"}, "scripts": {"build": "x", "test:unit": "y"}}',
        "Makefile": ".PHONY: lint\n\nbuild: deps\n\ttrue\n\nlint:\n\ttrue\n\nout/%.o: %.c\n\ttrue\n",
        "README.md": "# acme\n",
    }, use_git=False)
    p = scan_project(Repo(root, use_git=False))
    assert {"acme", "acme-web"} <= set(p.commands)
    assert {"acme-tool", "web"} <= p.names
    assert set(p.npm_scripts) == {"build", "test:unit"}
    assert {"build", "lint"} <= set(p.make_targets)
    assert p.make_targets["build"] == "Makefile:3"
    assert "out/%.o" in p.make_patterns
    assert p.make_dynamic is False
    assert "acme" in p.python_packages


def test_makefile_with_generated_include_is_dynamic(make_repo):
    root = make_repo({"Makefile": "include build/generated.mk\n\nall:\n\ttrue\n", "README.md": "# x\n"}, use_git=False)
    assert scan_project(Repo(root, use_git=False)).make_dynamic is True


def test_broken_package_json_is_ignored(make_repo):
    root = make_repo({"package.json": "{not json", "README.md": "# x\n"}, use_git=False)
    p = scan_project(Repo(root, use_git=False))
    assert p.npm_scripts == {} and p.has_package_json is False
