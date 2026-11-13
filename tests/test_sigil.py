"""Tests for the Sigil interpreter. Run: python -m unittest discover -s tests -v"""
import contextlib
import datetime as dt
import io
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sigil  # noqa: E402


def run_sigil(source: str, stdin: str = "") -> str:
    """Run Sigil source, return stdout. Raises sigil.SigilError on language errors."""
    lines = sigil.parse_lines(source)
    statements, index = sigil.split_block(lines, 0, 0)
    assert index == len(lines)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin)):
        sigil.run(statements, {}, {})
    return out.getvalue()


def out_lines(source: str, stdin: str = "") -> list[str]:
    return run_sigil(source, stdin).splitlines()


def error_of(source: str, stdin: str = "") -> str:
    try:
        run_sigil(source, stdin)
    except sigil.SigilError as exc:
        return str(exc)
    raise AssertionError("expected SigilError")


class Strings(unittest.TestCase):
    def test_sigils_inside_quotes_untouched(self):
        self.assertEqual(out_lines(">: 'cost %a $x #rnd ! & |'"), ["cost %a $x #rnd ! & |"])

    def test_true_false_inside_quotes_untouched(self):
        self.assertEqual(out_lines(">: 'untrue falsehood'"), ["untrue falsehood"])

    def test_concat_text_and_number(self):
        self.assertEqual(out_lines(">: 'кусок ' + 5"), ["кусок 5"])
        self.assertEqual(out_lines(">: '10' + 9"), ["109"])

    def test_backslash_is_literal(self):
        self.assertEqual(out_lines(r">: 'a\nb'"), [r"a\nb"])

    def test_comparison_with_string_compares_as_text(self):
        self.assertEqual(out_lines(">: '10' < 9"), ["True"])


class Comments(unittest.TestCase):
    def test_full_line_comment(self):
        self.assertEqual(out_lines("; 'комментарий'\n>: 1\n"), ["1"])

    def test_comment_without_quotes_and_with_odd_chars(self):
        self.assertEqual(out_lines("; don't %a $f #x ! & |\n>: 1\n"), ["1"])

    def test_trailing_comment(self):
        self.assertEqual(out_lines("%a = 3 ; три\n>: %a ; вывод\n"), ["3"])

    def test_semicolon_inside_string_is_text(self):
        self.assertEqual(out_lines(">: 'a;b' ; настоящий комментарий"), ["a;b"])

    def test_comment_after_block_header(self):
        self.assertEqual(out_lines("? true: ; заголовок\n\t>: 'ok'\n"), ["ok"])

    def test_comment_line_does_not_affect_indentation(self):
        src = "? true:\n; в нулевой колонке\n\t>: 'a'\n  ; два пробела, не кратно четырём\n\t>: 'b'\n"
        self.assertEqual(out_lines(src), ["a", "b"])

    def test_comment_between_if_and_else(self):
        src = "? false:\n\t>: 'yes'\n; перед else\n>\n\t>: 'no'\n"
        self.assertEqual(out_lines(src), ["no"])

    def test_only_comments_is_empty_program(self):
        self.assertEqual(run_sigil("; 1\n  ; 2\n"), "")

    def test_semicolon_in_comment_after_string(self):
        self.assertEqual(out_lines(">: 'x' ; 'y;z'"), ["x"])


class Membership(unittest.TestCase):
    def test_in_and_not_in(self):
        self.assertEqual(out_lines(">: 'r' ~ 'rps'"), ["True"])
        self.assertEqual(out_lines(">: 'x' ~ 'rps'"), ["False"])
        self.assertEqual(out_lines(">: 'x' !~ 'rps'"), ["True"])
        self.assertEqual(out_lines(">: 'r' !~ 'rps'"), ["False"])

    def test_substring_semantics(self):
        self.assertEqual(out_lines(">: 'rp' ~ 'rps'"), ["True"])
        self.assertEqual(out_lines(">: 'sp' ~ 'rps'"), ["False"])

    def test_empty_left_is_never_inside(self):
        self.assertEqual(out_lines(">: '' ~ 'rps'"), ["False"])
        self.assertEqual(out_lines(">: '' !~ 'rps'"), ["True"])

    def test_number_is_converted_to_text(self):
        self.assertEqual(out_lines(">: 2 ~ 12345"), ["True"])
        self.assertEqual(out_lines(">: 9 ~ 12345"), ["False"])

    def test_variables_and_combination(self):
        self.assertEqual(out_lines("%m = 'p'\n>: %m ~ 'rps' & 1 < 2"), ["True"])
        self.assertEqual(out_lines("%m = 'p'\n>: !(%m ~ 'rps')"), ["False"])
        self.assertEqual(out_lines("%m = 'x'\n>: %m !~ 'rps' | 1 > 2"), ["True"])

    def test_tilde_inside_string_is_text(self):
        self.assertEqual(out_lines(">: 'a ~ b !~ c'"), ["a ~ b !~ c"])

    def test_not_equal_and_not_still_work_next_to_tilde(self):
        self.assertEqual(out_lines(">: 1 != 2 & !(3 == 4) & 'a' !~ 'b'"), ["True"])


class Len(unittest.TestCase):
    def test_len_of_text_and_number(self):
        self.assertEqual(out_lines(">: #len('hello')"), ["5"])
        self.assertEqual(out_lines(">: #len('')"), ["0"])
        self.assertEqual(out_lines(">: #len(12345)"), ["5"])
        self.assertEqual(out_lines("%s = 'абв'\n>: #len(%s)"), ["3"])

    def test_len_in_expression(self):
        self.assertEqual(out_lines(">: #len('ab') + 1"), ["3"])
        self.assertEqual(out_lines(">: #len('ab') == 2"), ["True"])

    def test_len_argument_count(self):
        self.assertIn("exactly one argument", error_of(">: #len('a', 'b')"))
        self.assertIn("exactly one argument", error_of(">: #len"))

    def test_len_hint_for_typo(self):
        self.assertIn("did you mean #len?", error_of(">: #lne('a')"))


class Logic(unittest.TestCase):
    def test_and_or_not(self):
        self.assertEqual(out_lines(">: 1 < 2 & 2 < 3"), ["True"])
        self.assertEqual(out_lines(">: 1 > 2 | 2 < 3"), ["True"])
        self.assertEqual(out_lines(">: !(1 == 1)"), ["False"])

    def test_not_equal_still_works(self):
        self.assertEqual(out_lines(">: 5 != 5"), ["False"])
        self.assertEqual(out_lines(">: 5 != 6"), ["True"])

    def test_not_binds_looser_than_comparison(self):
        self.assertEqual(out_lines("%a = 5\n>: !%a == 6"), ["True"])

    def test_true_false_literals(self):
        self.assertEqual(out_lines(">: true & !false"), ["True"])

    def test_short_circuit(self):
        # right side would raise (division by zero) if evaluated
        self.assertEqual(out_lines(">: 1 > 2 & 1 / 0 > 1"), ["False"])
        self.assertEqual(out_lines(">: 1 < 2 | 1 / 0 > 1"), ["True"])


class ControlFlow(unittest.TestCase):
    def test_if_elif_else(self):
        src = "? %x > 5:\n\t>: 'big'\n> ? %x == 5:\n\t>: 'eq'\n>\n\t>: 'small'\n"
        for x, expected in ((9, "big"), (5, "eq"), (1, "small")):
            self.assertEqual(out_lines(f"%x = {x}\n" + src), [expected])

    def test_while(self):
        self.assertEqual(out_lines("%a = 3\n@%a > 0:\n\t>: %a\n\t%a = %a - 1\n"), ["3", "2", "1"])

    def test_loop_limit(self):
        with mock.patch.object(sigil, "MAX_LOOP_ITERATIONS", 100):
            self.assertIn("exceeded 100 iterations", error_of("@true:\n\t%a = 1\n"))

    def test_loop_limit_default(self):
        self.assertEqual(sigil.MAX_LOOP_ITERATIONS, 1_000_000)

    def test_four_spaces_equal_tab(self):
        self.assertEqual(out_lines("? true:\n    >: 'ok'\n"), ["ok"])


class Functions(unittest.TestCase):
    def test_call_and_return(self):
        self.assertEqual(out_lines("$sum(%a, %b):\n\t:< %a + %b\n>: $sum(2, 3)\n"), ["5"])

    def test_recursion(self):
        src = "$f(%n):\n\t? %n == 0:\n\t\t:< 0\n\t:< $f(%n - 1) + 1\n>: $f(20)\n"
        self.assertEqual(out_lines(src), ["20"])

    def test_wrong_arg_count(self):
        self.assertIn("expects 2", error_of("$s(%a, %b):\n\t:< %a\n>: $s(1)\n"))

    def test_return_outside_function(self):
        self.assertIn("inside a function", error_of(":< 1\n"))

    def test_local_assignment_does_not_leak(self):
        src = "%a = 1\n$f():\n\t%a = 2\n\t:< 0\n%r = $f()\n>: %a\n"
        self.assertEqual(out_lines(src), ["1"])


class SystemCalls(unittest.TestCase):
    def test_date(self):
        self.assertEqual(out_lines(">: #date"), [dt.date.today().strftime("%d.%m.%Y")])

    def test_rnd_forms(self):
        for _ in range(50):
            self.assertTrue(0 <= int(out_lines(">: #rnd")[0]) <= 100)
            self.assertTrue(1 <= int(out_lines(">: #rnd(1, 10)")[0]) <= 10)
            self.assertIn(out_lines(">: #rnd('abc')")[0], "abc")
            code = out_lines(">: #rnd(5, 'abc')")[0]
            self.assertEqual(len(code), 5)
            self.assertTrue(set(code) <= set("abc"))

    def test_rnd_bad_range(self):
        self.assertIn("lower bound", error_of(">: #rnd(10, 1)"))

    def test_unknown_call_with_hint(self):
        msg = error_of(">: #data")
        self.assertIn("unknown system call: #data", msg)
        self.assertIn("did you mean #date?", msg)

    def test_unknown_call_without_hint(self):
        msg = error_of(">: #zzzzzz")
        self.assertIn("unknown system call: #zzzzzz", msg)
        self.assertNotIn("did you mean", msg)

    def test_hash_inside_quotes_is_not_a_call(self):
        self.assertEqual(out_lines(">: '#data'"), ["#data"])


class Errors(unittest.TestCase):
    def test_undefined_variable(self):
        self.assertIn("undefined variable: %zz", error_of(">: %zz"))

    def test_division_by_zero(self):
        self.assertIn("division by zero", error_of(">: 1 / 0"))

    def test_error_has_line_number(self):
        self.assertTrue(error_of("%a = 1\n>: %zz").startswith("line 2:"))

    def test_error_reports_only_innermost_line(self):
        # error is on line 4, inside a loop (line 2) inside an if (line 1)
        src = "? true:\n\t@true:\n\t\t%a = 1\n\t\t>: %zz\n"
        msg = error_of(src)
        self.assertEqual(msg, "line 4: undefined variable: %zz")

    def test_error_inside_function_reports_function_line(self):
        src = "$f(%n):\n\t:< 1 / %n\n>: $f(0)\n"
        self.assertEqual(error_of(src), "line 2: division by zero")

    def test_bad_indentation(self):
        with self.assertRaises(sigil.SigilError):
            sigil.parse_lines("? true:\n  >: 'two spaces'\n")

    def test_else_without_if(self):
        with self.assertRaises(sigil.SigilError):
            sigil.split_block(sigil.parse_lines(">\n\t>: 'x'\n"), 0, 0)

    def test_unknown_statement(self):
        self.assertIn("unknown statement", error_of("hello\n"))


class InputParsing(unittest.TestCase):
    def test_numbers_and_text(self):
        src = "%a = <:\n%b = <:\n%c = <:\n>: %a + 1\n>: %b + 1\n>: %c\n"
        self.assertEqual(out_lines(src, "41\n1.5\nabc\n"), ["42", "2.5", "abc"])

    def test_eof(self):
        self.assertIn("input ended", error_of("%a = <:\n", ""))


class Colors(unittest.TestCase):
    # Regression values: what the current mapping yields, not an external spec.
    def test_known_codes(self):
        self.assertEqual(sigil.hustl_console_color("E2"), 143)
        self.assertEqual(sigil.hustl_console_color("E2.210"), 233)
        self.assertEqual(sigil.hustl_console_color("A9.750"), 232)

    def test_range(self):
        for letter in "AMZ":
            for digit in "059":
                self.assertTrue(16 <= sigil.hustl_console_color(f"{letter}{digit}") <= 255)

    def test_longer_suffix_accepted(self):
        sigil.hustl_console_color("E2.21012345")

    def test_invalid(self):
        for bad in ("e2", "E", "EE", "E22x"):
            with self.assertRaises(sigil.SigilError):
                sigil.hustl_console_color(bad)

    def test_colored_output_escape(self):
        self.assertEqual(out_lines(">:E2 'x'"), ["\x1b[38;5;143mx\x1b[0m"])


class ExamplePrograms(unittest.TestCase):
    def run_file(self, name, stdin=""):
        return out_lines((ROOT / name).read_text(encoding="utf-8"), stdin)

    def test_calculator(self):
        cases = {"3\n+\n4\n": "7", "3\n-\n4\n": "-1", "3\n*\n4\n": "12", "8\n/\n4\n": "2.0"}
        for stdin, expected in cases.items():
            self.assertEqual(self.run_file("main.sg", stdin)[-1], expected)

    def test_calculator_edge_cases(self):
        self.assertEqual(self.run_file("main.sg", "3\n/\n0\n")[-1], "Error: division by zero")
        self.assertEqual(self.run_file("main.sg", "3\n^\n4\n")[-1], "Error: unknown operation")

    def test_other_examples_run(self):
        # logic_example.sg is excluded: it ends with a deliberate deep recursion
        for name in ("function_example.sg", "loop_example.sg", "rnd_example.sg", "color_example.sg"):
            self.run_file(name)

    def play_guess_game(self, number_guesses):
        # Number round: the given guesses; letter round: leftovers (never match), then a..z.
        letters = "\n".join("abcdefghijklmnopqrstuvwxyz")
        return self.run_file("guess_game.sg", "\n".join(map(str, number_guesses)) + "\n" + letters + "\n")

    def score_of(self, output):
        import re
        return float(re.search(r"Score: (-?\d+(?:\.\d+)?)", "\n".join(output)).group(1))

    def test_guess_game_score_never_negative(self):
        # 0 is outside 1..10, so these are guaranteed misses: 12 misses + at least 1 hit > limit
        self.assertEqual(self.score_of(self.play_guess_game([0] * 12 + list(range(1, 11)))), 0)

    def test_guess_game_score_in_range(self):
        # sequential guesses 1..10 need between 1 and 10 tries -> score 10..100
        self.assertTrue(10 <= self.score_of(self.play_guess_game(range(1, 11))) <= 100)

    def play_rps(self, cpu_move, inputs):
        class FixedRandom:
            def choice(self, seq):
                return cpu_move
        with mock.patch.object(sigil.random, "SystemRandom", FixedRandom):
            return "\n".join(self.run_file("rps.sg", "\n".join(inputs) + "\n"))

    def test_rps_player_wins_three_zero(self):
        out = self.play_rps("s", ["r", "r", "r"])  # rock beats scissors
        self.assertIn("Счёт 3:0", out)
        self.assertIn("Вы победили!", out)
        self.assertNotIn("Компьютер победил", out)

    def test_rps_computer_wins(self):
        out = self.play_rps("p", ["r", "r", "r"])  # paper beats rock
        self.assertIn("Счёт 0:3", out)
        self.assertIn("Компьютер победил", out)

    def test_rps_draws_do_not_score(self):
        out = self.play_rps("r", ["r", "r", "p", "p", "p"])
        self.assertEqual(out.count("Ничья"), 2)
        self.assertIn("Раунд 5", out)
        self.assertIn("Счёт 3:0", out)

    def test_rps_invalid_input_is_reprompted(self):
        out = self.play_rps("s", ["x", "9", "", "r", "r", "r"])
        self.assertEqual(out.count("Нужно r, p или s:"), 3)
        self.assertIn("Вы победили!", out)
        self.assertIn("Раунд 3", out)
        self.assertNotIn("Раунд 4", out)  # bad input does not burn rounds

    def test_rps_rejects_substrings_and_empty(self):
        # 'rp', 'rps' and '' are inside 'rps' or empty, but are not a single valid move
        out = self.play_rps("s", ["rp", "rps", "sp", "", "r", "r", "r"])
        self.assertEqual(out.count("Нужно r, p или s:"), 4)
        self.assertIn("Вы победили!", out)

    def test_rps_every_pairing(self):
        wins = [("r", "s"), ("s", "p"), ("p", "r")]  # (player, cpu) -> player wins
        for me in "rps":
            for cpu in "rps":
                if me == cpu:
                    continue  # a draw never ends the game; covered by test_rps_draws_do_not_score
                out = self.play_rps(cpu, [me] * 5)
                if (me, cpu) in wins:
                    self.assertIn("Вы победили!", out, (me, cpu))
                else:
                    self.assertIn("Компьютер победил", out, (me, cpu))

    def test_comment_example(self):
        self.assertEqual(self.run_file("comment_example.sg"),
                         ["3", "2", "1", "точка с запятой; внутри строки — это просто текст"])


if __name__ == "__main__":
    unittest.main()
