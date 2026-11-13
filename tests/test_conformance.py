"""Language-level conformance suite: a program, its input and the exact expected output.

The cases live in tests/conformance/*.cases and know nothing about Python. They are run through the
command line, so ANY implementation of Sigil can be checked against them, for example a port:

    python -m unittest tests.test_conformance                  # the reference (sigil.py)
    SIGIL_CMD="path/to/sigil.exe" python -m unittest tests.test_conformance

Contract for an implementation: `<command> program.sg` reads stdin and writes stdout/stderr as UTF-8,
prints a runtime/parse error as `Sigil error: <message>` on stderr and exits with code 1 (0 on success).

Case file format (a line starting with '=== ' or '--- ' is always a marker, never program text):

    === case-name
    --- sg          program text                     (<TAB> stands for a tab character)
    --- in          standard input, optional
    --- out         expected stdout                  (<ESC> stands for the escape character)
    --- err         expected stderr, exact; implies exit code 1
    --- err~        expected stderr must CONTAIN this text; implies exit code 1

Blank lines at the end of a section are ignored. Without an `err` section, stderr must be empty and
the exit code 0.
"""
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CASES_DIR = HERE / "conformance"
SECTIONS = ("sg", "in", "out", "err", "err~")


def split_command(text: str):
    """Split SIGIL_CMD into arguments. POSIX rules would eat the backslashes of Windows paths,
    so on Windows the text is split without them and surrounding quotes are removed by hand."""
    if os.name != "nt":
        return shlex.split(text)
    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] and part[0] in "'\"" else part
            for part in shlex.split(text, posix=False)]


def implementation_command():
    custom = os.environ.get("SIGIL_CMD")
    return split_command(custom) if custom else [sys.executable, str(ROOT / "sigil.py")]


def parse_cases(text: str, origin: str):
    """Return [(name, {section: text})] from the contents of a .cases file."""
    cases, name, sections, current, lines = [], None, None, None, []

    def close_section():
        if sections is not None and current is not None:
            while lines and not lines[-1].strip():
                lines.pop()
            sections[current] = "".join(line + "\n" for line in lines)

    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("=== "):
            close_section()
            if name is not None:
                cases.append((name, sections))
            name, sections, current, lines = line[4:].strip(), {}, None, []
        elif line.startswith("--- "):
            close_section()
            current, lines = line[4:].strip(), []
            if current not in SECTIONS:
                raise ValueError(f"{origin}:{number}: unknown section {current!r}")
            if name is None:
                raise ValueError(f"{origin}:{number}: section before the first '=== name'")
            if current in sections:
                raise ValueError(f"{origin}:{number}: duplicate section {current!r} in {name!r}")
        elif current is not None:
            lines.append(line)
        elif line.strip():
            raise ValueError(f"{origin}:{number}: text outside of a section: {line!r}")
    close_section()
    if name is not None:
        cases.append((name, sections))
    for case_name, case_sections in cases:
        if "sg" not in case_sections:
            raise ValueError(f"{origin}: case {case_name!r} has no 'sg' section")
        if "err" in case_sections and "err~" in case_sections:
            raise ValueError(f"{origin}: case {case_name!r} has both 'err' and 'err~'")
    return cases


def load_all_cases():
    cases, seen = [], {}
    for path in sorted(CASES_DIR.glob("*.cases")):
        for name, sections in parse_cases(path.read_text(encoding="utf-8"), path.name):
            if name in seen:
                raise ValueError(f"duplicate case name {name!r} in {path.name} and {seen[name]}")
            seen[name] = path.name
            cases.append((path.stem, name, sections))
    return cases


def run_case(sections: dict):
    program = sections["sg"].replace("<TAB>", "\t")
    stdin = sections.get("in", "").replace("<TAB>", "\t")
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "case.sg"
        path.write_text(program, encoding="utf-8", newline="\n")
        done = subprocess.run(implementation_command() + [str(path)], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", env=environment, timeout=60)
    return done.stdout.replace("\r\n", "\n"), done.stderr.replace("\r\n", "\n"), done.returncode


class Conformance(unittest.TestCase):
    pass


def make_test(group, name, sections):
    def test(self):
        stdout, stderr, code = run_case(sections)
        expected_out = sections.get("out", "").replace("<ESC>", "\x1b")
        self.assertEqual(stdout, expected_out, f"stdout of {group}/{name}")
        if "err" in sections:
            self.assertEqual(stderr, sections["err"].replace("<ESC>", "\x1b"), f"stderr of {group}/{name}")
            self.assertEqual(code, 1, "an error must exit with code 1")
        elif "err~" in sections:
            self.assertIn(sections["err~"].strip(), stderr, f"stderr of {group}/{name}")
            self.assertEqual(code, 1, "an error must exit with code 1")
        else:
            self.assertEqual(stderr, "", f"unexpected stderr in {group}/{name}")
            self.assertEqual(code, 0, f"exit code of {group}/{name}")
    return test


for _group, _name, _sections in load_all_cases():
    setattr(Conformance, f"test_{_group}__{_name.replace('-', '_')}", make_test(_group, _name, _sections))


class CaseFormat(unittest.TestCase):
    """The format parser itself (so a mistake in a case file is reported as such)."""

    def test_parse_basic(self):
        text = "=== a\n--- sg\n>: 1\n\n--- out\n1\n\n=== b\n--- sg\n>: 2\n--- err~\nboom\n"
        self.assertEqual(parse_cases(text, "t"), [
            ("a", {"sg": ">: 1\n", "out": "1\n"}),
            ("b", {"sg": ">: 2\n", "err~": "boom\n"}),
        ])

    def test_blank_line_inside_a_section_is_kept(self):
        self.assertEqual(parse_cases("=== a\n--- sg\n>: 1\n\n>: 2\n", "t")[0][1]["sg"], ">: 1\n\n>: 2\n")

    def test_errors(self):
        for bad in ("--- sg\nx\n", "=== a\n--- nope\nx\n", "=== a\nstray\n", "=== a\n--- out\n1\n",
                    "=== a\n--- sg\n1\n--- sg\n2\n", "=== a\n--- sg\n1\n--- err\n1\n--- err~\n1\n"):
            with self.assertRaises(ValueError, msg=bad):
                parse_cases(bad, "t")

    def test_command_splitting_keeps_windows_paths(self):
        if os.name == "nt":
            self.assertEqual(split_command(r"python D:\1_WORK\My Dir\sigil.py".replace("My Dir", "dir")),
                             ["python", r"D:\1_WORK\dir\sigil.py"])
            self.assertEqual(split_command(r'"C:\Program Files\Sigil\sigil.exe" --flag'),
                             [r"C:\Program Files\Sigil\sigil.exe", "--flag"])
        else:
            self.assertEqual(split_command("python '/a b/sigil.py'"), ["python", "/a b/sigil.py"])

    def test_case_names_are_unique_and_there_are_cases(self):
        names = [name for _, name, _ in load_all_cases()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreater(len(names), 20)


if __name__ == "__main__":
    unittest.main()
