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


class Lists(unittest.TestCase):
    def test_literal_and_print(self):
        self.assertEqual(out_lines(">: [1, 'a', 2.5]"), ["[1, 'a', 2.5]"])
        self.assertEqual(out_lines(">: []"), ["[]"])
        self.assertEqual(out_lines(">: [[1, 2], ['x']]"), ["[[1, 2], ['x']]"])

    def test_sigils_inside_list_strings_are_text(self):
        self.assertEqual(out_lines(">: ['a;b', '%x', '~', '#len']"), ["['a;b', '%x', '~', '#len']"])

    def test_index_read(self):
        self.assertEqual(out_lines("%l = [10, 20, 30]\n>: %l[0]\n>: %l[2]"), ["10", "30"])
        self.assertEqual(out_lines("%l = [10, 20, 30]\n%i = 1\n>: %l[%i + 1]"), ["30"])
        self.assertEqual(out_lines("%m = [[1, 2], [3, 4]]\n>: %m[1][0]"), ["3"])

    def test_text_can_be_indexed(self):
        self.assertEqual(out_lines(">: 'abc'[1]"), ["b"])

    def test_index_errors(self):
        self.assertIn("index 3 out of range (length 3)", error_of("%l = [1, 2, 3]\n>: %l[3]"))
        self.assertIn("index -1 out of range", error_of("%l = [1, 2, 3]\n>: %l[-1]"))
        self.assertIn("whole number", error_of("%l = [1]\n>: %l[0.0]"))
        self.assertIn("whole number", error_of("%l = [1]\n>: %l['a']"))
        self.assertIn("whole number", error_of("%l = [1]\n>: %l[true]"))
        self.assertIn("only lists and text", error_of("%n = 5\n>: %n[0]"))
        self.assertIn("out of range", error_of("%l = []\n>: %l[0]"))

    def test_index_assignment(self):
        self.assertEqual(out_lines("%l = [1, 2, 3]\n%l[1] = 'x'\n>: %l"), ["[1, 'x', 3]"])
        self.assertEqual(out_lines("%l = [1, 2, 3]\n%l[#len(%l) - 1] = 0\n>: %l"), ["[1, 2, 0]"])
        self.assertEqual(out_lines("%l = [1, 2, 3]\n%i = 0\n%l[%i + 1] = 9\n>: %l"), ["[1, 9, 3]"])
        self.assertEqual(out_lines("%m = [[1, 2], [3, 4]]\n%m[1][0] = 9\n>: %m"), ["[[1, 2], [9, 4]]"])

    def test_index_assignment_from_input(self):
        self.assertEqual(out_lines("%l = [0]\n%l[0] = <:\n>: %l", "7\n"), ["[7]"])

    def test_assignment_errors(self):
        self.assertIn("out of range", error_of("%l = [1]\n%l[1] = 5"))
        self.assertIn("undefined variable: %zz", error_of("%zz[0] = 1"))
        self.assertIn("read-only", error_of("%s = 'abc'\n%s[0] = 'x'"))
        self.assertIn("empty or unclosed", error_of("%l = [1]\n%l[] = 5"))
        self.assertIn("unknown statement: %l[0 = 5", error_of("%l = [1]\n%l[0 = 5"))  # '=' inside brackets
        self.assertIn("assignment target", error_of("5 = 1"))

    def test_comparison_line_is_not_an_assignment(self):
        self.assertIn("unknown statement", error_of("%a = 1\n%a == 1"))
        self.assertIn("unknown statement", error_of("%a = 1\n%a <= 1"))

    # --- lists are values, not references -------------------------------------------------
    def test_assignment_copies(self):
        src = "%a = [1, 2]\n%b = %a\n%b[0] = 99\n>: %a\n>: %b"
        self.assertEqual(out_lines(src), ["[1, 2]", "[99, 2]"])

    def test_nested_assignment_copies_deeply(self):
        src = "%a = [[1], [2]]\n%b = %a\n%b[0][0] = 99\n>: %a\n>: %b"
        self.assertEqual(out_lines(src), ["[[1], [2]]", "[[99], [2]]"])

    def test_literal_containing_a_list_copies_it(self):
        src = "%a = [1]\n%b = [%a, %a]\n%a[0] = 5\n%b[0][0] = 7\n>: %a\n>: %b"
        self.assertEqual(out_lines(src), ["[5]", "[[7], [1]]"])

    def test_function_parameter_is_a_copy(self):
        src = "$f(%l):\n\t%l[0] = 99\n\t:< %l\n%a = [1, 2]\n%r = $f(%a)\n>: %a\n>: %r"
        self.assertEqual(out_lines(src), ["[1, 2]", "[99, 2]"])

    def test_function_cannot_modify_a_global_list(self):
        src = "%g = [1, 2]\n$f():\n\t%g[0] = 99\n\t:< %g[0]\n>: $f()\n>: %g"
        self.assertEqual(out_lines(src), ["99", "[1, 2]"])

    def test_returned_list_is_independent(self):
        src = "$f():\n\t%x = [1]\n\t:< %x\n%a = $f()\n%b = $f()\n%a[0] = 5\n>: %b"
        self.assertEqual(out_lines(src), ["[1]"])

    # --- #add / #len / ~ -------------------------------------------------------------------
    def test_add_returns_new_list(self):
        self.assertEqual(out_lines("%a = [1]\n%b = #add(%a, 2)\n>: %a\n>: %b"), ["[1]", "[1, 2]"])

    def test_add_in_loop_builds_list(self):
        src = "%l = []\n%i = 0\n@%i < 3:\n\t%l = #add(%l, %i * 10)\n\t%i = %i + 1\n>: %l"
        self.assertEqual(out_lines(src), ["[0, 10, 20]"])

    def test_add_copies_the_added_value(self):
        self.assertEqual(out_lines("%a = [1]\n%l = #add([], %a)\n%a[0] = 5\n>: %l"), ["[[1]]"])

    def test_add_as_bare_statement_is_an_error(self):
        # lists are values: the result must be assigned back
        self.assertIn("unknown statement", error_of("%l = [1]\n#add(%l, 2)"))

    def test_add_errors(self):
        self.assertIn("first argument", error_of(">: #add(5, 1)"))
        self.assertIn("two arguments", error_of(">: #add([1])"))
        self.assertIn("two arguments", error_of(">: #add"))

    def test_len_of_list(self):
        self.assertEqual(out_lines(">: #len([1, 2, 3])"), ["3"])
        self.assertEqual(out_lines(">: #len([])"), ["0"])
        self.assertEqual(out_lines(">: #len([[1, 2]])"), ["1"])

    def test_membership_is_by_element(self):
        self.assertEqual(out_lines(">: 'b' ~ ['a', 'b']"), ["True"])
        self.assertEqual(out_lines(">: 'z' ~ ['a', 'b']"), ["False"])
        self.assertEqual(out_lines(">: 'z' !~ ['a', 'b']"), ["True"])
        self.assertEqual(out_lines(">: 2 ~ [1, 2, 3]"), ["True"])
        self.assertEqual(out_lines(">: [1] ~ [[1], [2]]"), ["True"])

    def test_membership_is_not_substring_inside_a_list(self):
        self.assertEqual(out_lines(">: 'a' ~ ['abc']"), ["False"])

    def test_membership_number_equals_text_like_double_equals(self):
        self.assertEqual(out_lines(">: 1 ~ ['1']"), ["True"])
        self.assertEqual(out_lines(">: 1 == '1'"), ["True"])

    def test_empty_text_in_list_is_a_normal_element(self):
        self.assertEqual(out_lines(">: '' ~ ['']"), ["True"])
        self.assertEqual(out_lines(">: '' ~ []"), ["False"])
        self.assertEqual(out_lines(">: '' ~ 'abc'"), ["False"])  # text rule unchanged

    # --- operators -------------------------------------------------------------------------
    def test_concatenation_and_repeat(self):
        self.assertEqual(out_lines(">: [1] + [2, 3]"), ["[1, 2, 3]"])
        self.assertEqual(out_lines(">: [0] * 3"), ["[0, 0, 0]"])
        self.assertEqual(out_lines(">: 2 * [1]"), ["[1, 1]"])
        self.assertEqual(out_lines(">: 'L: ' + [1, 'a']"), ["L: [1, 'a']"])

    def test_repeat_is_capped(self):
        self.assertIn("would exceed", error_of(">: [0] * 100000000"))
        self.assertIn("would exceed", error_of(">: 'ab' * 100000000"))

    def test_equality_and_truthiness(self):
        self.assertEqual(out_lines(">: [1, 2] == [1, 2]"), ["True"])
        self.assertEqual(out_lines(">: [1, 2] == [2, 1]"), ["False"])
        self.assertEqual(out_lines("? []:\n\t>: 'yes'\n>\n\t>: 'no'"), ["no"])
        self.assertEqual(out_lines("? [0]:\n\t>: 'yes'\n>\n\t>: 'no'"), ["yes"])

    def test_invalid_operations_are_sigil_errors_not_python_tracebacks(self):
        self.assertTrue(error_of(">: [1] + 1").startswith("line 1: invalid operation"))
        self.assertTrue(error_of(">: 'a' - 1").startswith("line 1: invalid operation"))
        self.assertTrue(error_of(">: [1] < 2").startswith("line 1: invalid operation"))

    def test_algorithm_sum_and_max(self):
        src = ("%l = [4, 9, 2]\n%sum = 0\n%max = %l[0]\n%i = 0\n@%i < #len(%l):\n"
               "\t%sum = %sum + %l[%i]\n\t? %l[%i] > %max:\n\t\t%max = %l[%i]\n\t%i = %i + 1\n>: %sum\n>: %max")
        self.assertEqual(out_lines(src), ["15", "9"])


class Num(unittest.TestCase):
    def test_integers(self):
        for text, expected in (("'42'", "42"), ("' -7 '", "-7"), ("'+5'", "5"), ("'0'", "0"), ("'007'", "7")):
            self.assertEqual(out_lines(f">: #num({text})"), [expected], text)

    def test_floats(self):
        for text, expected in (("'2.5'", "2.5"), ("'.5'", "0.5"), ("'5.'", "5.0"), ("'-0.25'", "-0.25")):
            self.assertEqual(out_lines(f">: #num({text})"), [expected], text)

    def test_result_is_a_real_number(self):
        self.assertEqual(out_lines(">: #num('3') + #num('4')"), ["7"])
        self.assertEqual(out_lines(">: #num('5') / 2"), ["2.5"])
        self.assertEqual(out_lines(">: #num('10') > #num('9')"), ["True"])  # numbers, not text order
        self.assertEqual(out_lines(">: '10' > '9'"), ["False"])
        self.assertEqual(out_lines(">: #num('3') + '4'"), ["34"])  # + with text is still concatenation

    def test_number_passes_through_unchanged(self):
        self.assertEqual(out_lines(">: #num(5)"), ["5"])
        self.assertEqual(out_lines(">: #num(2.5)"), ["2.5"])
        # a float whose text form is '1e+20' must not be re-parsed as text
        self.assertEqual(out_lines("%x = 100000000000.0 * 100000000000.0\n>: #num(%x) == %x"), ["True"])

    def test_not_a_number_is_an_error_naming_the_text(self):
        for text in ("'abc'", "''", "' '", "'1,5'", "'1e5'", "'12abc'", "'--1'", "'1.2.3'", "'٣'"):
            message = error_of(f">: #num({text})")
            self.assertIn("#num cannot convert", message, text)
            self.assertTrue(message.startswith("line 1:"), text)
        self.assertIn("cannot convert 'abc' to a number", error_of(">: #num('abc')"))

    def test_other_types_are_errors(self):
        for expression in ("[1]", "true", "#date"):
            self.assertIn("#num cannot convert", error_of(f">: #num({expression})"), expression)

    def test_argument_count(self):
        self.assertIn("#num expects exactly one argument", error_of(">: #num('1', '2')"))
        self.assertIn("#num expects exactly one argument", error_of(">: #num"))

    def test_typo_hint(self):
        self.assertIn("did you mean #num?", error_of(">: #nun('1')"))

    def test_sum_of_split_pieces(self):
        src = ("%p = #split('3 4 5', ' ')\n%i = 0\n%sum = 0\n@%i < #len(%p):\n"
               "\t%sum = %sum + #num(%p[%i])\n\t%i = %i + 1\n>: %sum")
        self.assertEqual(out_lines(src), ["12"])

    def test_join_split_num_round_trip(self):
        self.assertEqual(out_lines(">: #num(#join(#split('1 2 3', ' '), ''))"), ["123"])

    def test_input_and_num_agree_on_what_a_number_is(self):
        # <: reads these as numbers; #num accepts exactly the same spellings
        for spelling in ("41", "-3", "+3", "007", "1.5", ".5", "5."):
            from_input = out_lines("%a = <:\n>: %a + 1", spelling + "\n")
            from_num = out_lines(f">: #num('{spelling}') + 1")
            self.assertEqual(from_input, from_num, spelling)
        for spelling in ("1e5", "1,5", "abc", "٣"):
            self.assertEqual(out_lines("%a = <:\n>: %a + 1", spelling + "\n"), [spelling + "1"], spelling)
            self.assertIn("cannot convert", error_of(f">: #num('{spelling}')"), spelling)


class ForEach(unittest.TestCase):
    def test_over_list(self):
        self.assertEqual(out_lines("@%x : [10, 20, 30]:\n\t>: %x + 1"), ["11", "21", "31"])

    def test_over_text_goes_by_characters(self):
        self.assertEqual(out_lines("@%c : 'абв':\n\t>: %c"), ["а", "б", "в"])

    def test_over_variable_and_call_results(self):
        self.assertEqual(out_lines("%l = ['a', 'b']\n@%x : %l:\n\t>: %x"), ["a", "b"])
        self.assertEqual(out_lines("@%x : #split('p q', ' '):\n\t>: %x"), ["p", "q"])
        self.assertEqual(out_lines("$f():\n\t:< [1, 2]\n@%x : $f():\n\t>: %x"), ["1", "2"])

    def test_empty_list_and_empty_text_do_not_run_the_body(self):
        self.assertEqual(out_lines("@%x : []:\n\t>: 'body'\n>: 'after'"), ["after"])
        self.assertEqual(out_lines("@%x : '':\n\t>: 'body'\n>: 'after'"), ["after"])

    def test_variable_keeps_last_value_after_the_loop(self):
        self.assertEqual(out_lines("@%x : [1, 2, 3]:\n\t%y = 0\n>: %x"), ["3"])

    def test_empty_loop_leaves_the_variable_untouched(self):
        self.assertEqual(out_lines("%x = 'old'\n@%x : []:\n\t%y = 0\n>: %x"), ["old"])

    def test_sum_and_count(self):
        src = "%sum = 0\n@%n : [4, 9, 2]:\n\t%sum = %sum + %n\n>: %sum"
        self.assertEqual(out_lines(src), ["15"])

    def test_nested_loops(self):
        src = "@%a : [1, 2]:\n\t@%b : 'xy':\n\t\t>: %a + %b"
        self.assertEqual(out_lines(src), ["1x", "1y", "2x", "2y"])

    def test_loop_over_rows_of_lists(self):
        src = "%total = 0\n@%row : [[1, 2], [3]]:\n\t@%v : %row:\n\t\t%total = %total + %v\n>: %total"
        self.assertEqual(out_lines(src), ["6"])

    def test_snapshot_changing_the_list_inside_does_not_affect_iteration(self):
        src = "%l = [1, 2]\n@%x : %l:\n\t%l = #add(%l, 9)\n\t>: %x\n>: %l"
        self.assertEqual(out_lines(src), ["1", "2", "[1, 2, 9, 9]"])
        src = "%l = [1, 2, 3]\n@%x : %l:\n\t%l[2] = 0\n\t>: %x"
        self.assertEqual(out_lines(src), ["1", "2", "3"])  # element 3 was snapshotted, not 0

    def test_loop_variable_is_a_copy_of_the_element(self):
        src = "%l = [[1], [2]]\n@%row : %l:\n\t%row[0] = 99\n>: %l"
        self.assertEqual(out_lines(src), ["[[1], [2]]"])

    def test_return_from_inside_the_loop(self):
        src = ("$first(%l, %want):\n\t@%x : %l:\n\t\t? %x == %want:\n\t\t\t:< 'found'\n\t:< 'missing'\n"
               ">: $first([1, 2, 3], 2)\n>: $first([1, 2, 3], 7)")
        self.assertEqual(out_lines(src), ["found", "missing"])

    def test_loop_inside_function_does_not_leak_its_variable(self):
        src = "$f(%l):\n\t@%x : %l:\n\t\t%y = 1\n\t:< 0\n%r = $f([1])\n>: %x"
        self.assertIn("undefined variable: %x", error_of(src))

    def test_comment_after_header_and_with_inner_comment_line(self):
        src = "@%x : [1, 2]: ; 'по элементам'\n\t; внутри\n\t>: %x"
        self.assertEqual(out_lines(src), ["1", "2"])

    def test_spacing_variants(self):
        self.assertEqual(out_lines("@%x:[1]:\n\t>: %x"), ["1"])
        self.assertEqual(out_lines("@%x   :   [1]:\n\t>: %x"), ["1"])

    def test_errors(self):
        self.assertTrue(error_of("@%n : 5:\n\t>: 1").startswith("line 1: can only loop over a list or text"))
        self.assertIn("can only loop over", error_of("@%n : true:\n\t>: 1"))
        self.assertIn("can only loop over", error_of("@%n : #date:\n\t>: 1"))
        self.assertIn("expected a list or text after ':'", error_of("@%x : :\n\t>: 1"))
        # '@%x :' is just a while-loop on %x (the trailing ':' closes the header)
        self.assertIn("undefined variable: %x", error_of("@%x :\n\t>: 1"))
        self.assertIn("undefined variable: %nope", error_of("@%x : %nope:\n\t>: 1"))

    def test_error_inside_the_body_names_the_inner_line(self):
        self.assertEqual(error_of("@%x : [1]:\n\t>: %zz"), "line 2: undefined variable: %zz")

    def test_loop_over_huge_text_is_capped(self):
        with mock.patch.object(sigil, "MAX_LOOP_ITERATIONS", 5):
            self.assertIn("exceeded 5 iterations", error_of("@%x : 'abcdefgh':\n\t>: %x"))

    def test_while_loops_are_unchanged(self):
        self.assertEqual(out_lines("%a = 2\n@%a > 0:\n\t>: %a\n\t%a = %a - 1"), ["2", "1"])
        # a colon inside a string in a while condition is not mistaken for 'foreach'
        self.assertEqual(out_lines("%s = 'a:b'\n@%s == 'a:b':\n\t>: 'once'\n\t%s = 'x'"), ["once"])
        self.assertEqual(out_lines("%a = 'k'\n@%a ~ 'k:z':\n\t>: 'in'\n\t%a = 'q'"), ["in"])
        # text that merely looks like a header ('%b : ') inside a string of a while condition
        src = "%s = 'x'\n@%s != 'a %b : c':\n\t>: 'ok'\n\t%s = 'a %b : c'"
        self.assertEqual(out_lines(src), ["ok"])


class IsNum(unittest.TestCase):
    GOOD = ("'42'", "' -7 '", "'+5'", "'007'", "'2.5'", "'.5'", "'5.'", "5", "2.5", "-3")
    BAD = ("'abc'", "''", "' '", "'1,5'", "'1e5'", "'12abc'", "'--1'", "'1.2.3'", "'٣'", "[1]", "true", "#date")

    def test_true_for_numbers_and_numeric_text(self):
        for value in self.GOOD:
            self.assertEqual(out_lines(f">: #isnum({value})"), ["True"], value)

    def test_false_for_everything_else_and_never_an_error(self):
        for value in self.BAD:
            self.assertEqual(out_lines(f">: #isnum({value})"), ["False"], value)

    def test_agrees_with_num_on_every_sample(self):
        # #isnum is true exactly when #num succeeds
        for value in self.GOOD + self.BAD:
            if out_lines(f">: #isnum({value})") == ["True"]:
                out_lines(f">: #num({value})")  # must not raise
            else:
                self.assertIn("cannot convert", error_of(f">: #num({value})"), value)

    def test_agrees_with_input(self):
        for spelling in ("41", "-3", "+3", "007", "1.5", ".5", "5.", "1e5", "1,5", "abc", "٣", ""):
            read_as_number = out_lines("%a = <:\n>: #isnum(%a)", spelling + "\n")
            self.assertEqual(read_as_number, out_lines(f">: #isnum('{spelling}')"), spelling)

    def test_float_that_prints_with_an_exponent_is_still_a_number(self):
        self.assertEqual(out_lines("%x = 100000000000.0 * 100000000000.0\n>: #isnum(%x)"), ["True"])

    def test_works_with_not_in_conditions(self):
        src = "%v = 'x'\n? !#isnum(%v):\n\t>: 'not a number'\n>\n\t>: 'number'"
        self.assertEqual(out_lines(src), ["not a number"])
        self.assertEqual(out_lines(src.replace("'x'", "'12'")), ["number"])

    def test_reprompt_loop(self):
        src = ("%n = <:\n@!#isnum(%n):\n\t>: 'again'\n\t%n = <:\n>: %n + 1")
        self.assertEqual(out_lines(src, "x\n\n1,5\n41\n"), ["again", "again", "again", "42"])

    def test_argument_count_and_hint(self):
        self.assertIn("#isnum expects exactly one argument", error_of(">: #isnum('1', '2')"))
        self.assertIn("#isnum expects exactly one argument", error_of(">: #isnum"))
        self.assertIn("did you mean #isnum?", error_of(">: #isnun('1')"))


class JoinSplit(unittest.TestCase):
    def test_join_basic(self):
        self.assertEqual(out_lines(">: #join([1, 'a', 2.5], ', ')"), ["1, a, 2.5"])
        self.assertEqual(out_lines(">: #join(['a', 'b', 'c'], '')"), ["abc"])
        self.assertEqual(out_lines(">: #join(['x'], '-')"), ["x"])
        self.assertEqual(out_lines(">: #join([], '-')"), [""])

    def test_join_uses_text_without_quotes_and_nests_as_text(self):
        self.assertEqual(out_lines(">: #join(['a', [1, 'b']], '|')"), ["a|[1, 'b']"])

    def test_join_separator_is_converted_to_text(self):
        self.assertEqual(out_lines(">: #join([1, 2, 3], 0)"), ["10203"])

    def test_join_returns_text(self):
        self.assertEqual(out_lines(">: #len(#join(['ab', 'cd'], '--'))"), ["6"])

    def test_split_basic(self):
        self.assertEqual(out_lines(">: #split('a,b,c', ',')"), ["['a', 'b', 'c']"])
        self.assertEqual(out_lines(">: #split('цикл индекс', ' ')"), ["['цикл', 'индекс']"])
        self.assertEqual(out_lines(">: #split('a::b::c', '::')"), ["['a', 'b', 'c']"])

    def test_split_keeps_empty_pieces(self):
        self.assertEqual(out_lines(">: #split('a,,b', ',')"), ["['a', '', 'b']"])
        self.assertEqual(out_lines(">: #split(',a,', ',')"), ["['', 'a', '']"])
        self.assertEqual(out_lines(">: #split('', ',')"), ["['']"])

    def test_split_without_separator_in_text(self):
        self.assertEqual(out_lines(">: #split('abc', ',')"), ["['abc']"])

    def test_split_empty_separator_gives_characters(self):
        self.assertEqual(out_lines(">: #split('abc', '')"), ["['a', 'b', 'c']"])
        self.assertEqual(out_lines(">: #split('', '')"), ["[]"])
        self.assertEqual(out_lines(">: #len(#split('привет', ''))"), ["6"])

    def test_split_pieces_are_text_not_numbers(self):
        self.assertEqual(out_lines(">: #split('1,2', ',')[0] + 1"), ["11"])

    def test_split_number_argument_is_converted_to_text(self):
        self.assertEqual(out_lines(">: #split(12345, 3)"), ["['12', '45']"])

    def test_round_trip(self):
        src = "%s = 'a-b-c'\n>: #join(#split(%s, '-'), '-') == %s"
        self.assertEqual(out_lines(src), ["True"])

    def test_split_result_is_a_normal_list(self):
        src = "%w = #split('x y z', ' ')\n%w[1] = 'Q'\n%w = #add(%w, 'w')\n>: %w\n>: 'Q' ~ %w"
        self.assertEqual(out_lines(src), ["['x', 'Q', 'z', 'w']", "True"])

    def test_argument_errors(self):
        self.assertIn("#join expects exactly two arguments (list, separator)", error_of(">: #join([1])"))
        self.assertIn("#split expects exactly two arguments (text, separator)", error_of(">: #split('a')"))
        self.assertIn("#split expects exactly two arguments", error_of(">: #split"))
        self.assertIn("#join expects a list as the first argument", error_of(">: #join('abc', ',')"))

    def test_typo_hints(self):
        self.assertIn("did you mean #join?", error_of(">: #joyn([], ',')"))
        self.assertIn("did you mean #split?", error_of(">: #splt('a', ',')"))


class CaseCalls(unittest.TestCase):
    def test_lower_upper(self):
        self.assertEqual(out_lines(">: #lower('HeLLo')"), ["hello"])
        self.assertEqual(out_lines(">: #upper('HeLLo')"), ["HELLO"])

    def test_cyrillic(self):
        self.assertEqual(out_lines(">: #lower('ПРИВЕТ')"), ["привет"])
        self.assertEqual(out_lines(">: #upper('привет')"), ["ПРИВЕТ"])

    def test_number_becomes_text(self):
        self.assertEqual(out_lines(">: #lower(5) + 1"), ["51"])

    def test_with_variables_and_comparison(self):
        self.assertEqual(out_lines("%a = 'R'\n>: #lower(%a) == 'r'"), ["True"])

    def test_composition(self):
        self.assertEqual(out_lines(">: #len(#upper('abc'))"), ["3"])

    def test_argument_count_errors_name_the_call(self):
        self.assertIn("#lower expects exactly one argument", error_of(">: #lower('a', 'b')"))
        self.assertIn("#upper expects exactly one argument", error_of(">: #upper"))

    def test_typo_hint(self):
        self.assertIn("did you mean #lower?", error_of(">: #lowr('A')"))


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

    def test_rps_accepts_uppercase(self):
        out = self.play_rps("s", ["R", "r", "R"])
        self.assertEqual(out.count("Нужно r, p или s:"), 0)
        self.assertIn("Счёт 3:0", out)
        self.assertIn("Вы: камень", out)

    def test_rps_uppercase_after_reprompt(self):
        out = self.play_rps("s", ["x", "R", "R", "R"])
        self.assertEqual(out.count("Нужно r, p или s:"), 1)
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

    def play_hangman(self, letters, pick="low"):
        class FixedRandom:
            def randint(self, low, high):
                return low if pick == "low" else high   # word index: first ('цикл') or last ('сигил')
        with mock.patch.object(sigil.random, "SystemRandom", FixedRandom):
            return "\n".join(self.run_file("hangman.sg", "\n".join(letters) + "\n"))

    def test_hangman_win_without_mistakes(self):
        out = self.play_hangman(["ц", "и", "к", "л"])
        self.assertIn("Слово из 4 букв", out)
        self.assertIn("Вы выиграли! Слово: цикл", out)
        self.assertEqual(out.count("Нет такой буквы"), 0)
        self.assertIn("цик_   жизни: 6", out)

    def test_hangman_lose_after_six_mistakes(self):
        out = self.play_hangman(list("абвгде"))
        self.assertEqual(out.count("Нет такой буквы"), 6)
        self.assertIn("Вы проиграли. Слово было: цикл", out)
        self.assertNotIn("выиграли", out)
        self.assertIn("жизни: 1", out)

    def test_hangman_invalid_input_costs_nothing(self):
        # repeat, latin, digit, empty, two letters, repeated upper-case: six rejections, no lives lost
        out = self.play_hangman(["ц", "ц", "X", "5", "", "ци", "Ц", "и", "к", "л"])
        self.assertEqual(out.count("Нужна одна новая русская буква:"), 6)
        self.assertEqual(out.count("Нет такой буквы"), 0)
        self.assertIn("Вы выиграли! Слово: цикл", out)
        self.assertNotIn("жизни: 5", out)

    def test_hangman_accepts_uppercase(self):
        out = self.play_hangman(["Ц", "И", "К", "Л"])
        self.assertEqual(out.count("Нужна одна новая русская буква:"), 0)
        self.assertIn("Вы выиграли! Слово: цикл", out)

    def test_hangman_wrong_letters_are_listed_and_face_changes(self):
        out = self.play_hangman(["а", "ц", "и", "к", "л"])
        self.assertIn("Названы: а\n", out)  # joined with spaces, no quotes or brackets
        self.assertIn("Названы: а ц\n", out)
        self.assertIn("^_^  ", out)   # 5 lives left
        self.assertIn("жизни: 5", out)

    def test_hangman_repeated_letter_in_word(self):
        # 'сигил' contains 'и' twice: one guess opens both positions at once
        out = self.play_hangman(["и", "с", "г", "л"], pick="high")
        self.assertIn("_и_и_", out)
        self.assertEqual(out.count("Нет такой буквы"), 0)

    def test_hangman_picks_word_by_index(self):
        out = self.play_hangman(["с", "и", "г", "л"], pick="high")
        self.assertIn("Слово из 5 букв", out)
        self.assertIn("Вы выиграли! Слово: сигил", out)

    def test_sum_example(self):
        cases = {"3 4 5\n": "Чисел: 3, сумма: 12", "3  4   5\n": "Чисел: 3, сумма: 12",
                 "1.5 2.5 -1\n": "Чисел: 3, сумма: 3.0", "7\n": "Чисел: 1, сумма: 7", "\n": "Чисел: 0, сумма: 0"}
        for stdin, expected in cases.items():
            self.assertEqual(self.run_file("sum_example.sg", stdin)[-1], expected, repr(stdin))

    def test_sum_example_skips_bad_tokens_with_a_warning(self):
        out = "\n".join(self.run_file("sum_example.sg", "3 x 5 1,5\n"))
        self.assertIn("Пропущено, это не число: x", out)
        self.assertIn("Пропущено, это не число: 1,5", out)
        self.assertIn("Чисел: 2, сумма: 8", out)

    def test_sum_example_does_not_warn_about_empty_pieces(self):
        out = "\n".join(self.run_file("sum_example.sg", "  3   4  \n"))
        self.assertNotIn("Пропущено", out)
        self.assertIn("Чисел: 2, сумма: 7", out)

    def test_list_example(self):
        self.assertEqual(self.run_file("list_example.sg"), [
            "Было: [5, 3, 8, 1]",
            "Стало: [1, 3, 5, 8]",
            "Оригинал: [1, 3, 5, 8], копия: [100, 3, 5, 8]",
            "['a', 'b', 'c']",
            "True",
            "False",
        ])

    def test_comment_example(self):
        self.assertEqual(self.run_file("comment_example.sg"),
                         ["3", "2", "1", "точка с запятой; внутри строки — это просто текст"])


if __name__ == "__main__":
    unittest.main()
