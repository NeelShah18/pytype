import re
import textwrap

from pytype.pyi import parser
from pytype.pytd import pytd
from pytype.pytd.parse import parser as legacy_parser

import unittest


class _ParserTestBase(unittest.TestCase):

  def _check_legacy(self, src, actual):
    """Check that actual matches legacy parsing of src."""
    old_tree = legacy_parser.parse_string(src)
    self.assertMultiLineEqual(pytd.Print(old_tree), actual)

  def check(self, src, expected=None, prologue=None, legacy=True):
    """Check the parsing of src.

    This checks that parsing the source and then printing the resulting
    AST results in the expected text.  It also compares this to doing the
    same with the legacy parser.

    Args:
      src: A source string.
      expected: Optional expected result string.  If not provided, src is
        used instead.
      prologue: An optional prologue to be prepended to the expected text
        before comparisson.  Useful for imports that are introduced during
        printing the AST.
      legacy: If true, comapre results to legacy parser.
    """
    src = textwrap.dedent(src)
    expected = src if expected is None else textwrap.dedent(expected)
    if prologue:
      expected = "%s\n\n%s" % (textwrap.dedent(prologue), expected)
    actual = pytd.Print(parser.parse_string(src))
    if legacy:
      self._check_legacy(src, actual)
    self.assertMultiLineEqual(expected, actual)

  def check_error(self, src, expected_line, message):
    """Check that parsing the src raises the expected error."""
    try:
      pytd.Print(parser.parse_string(textwrap.dedent(src)))
      self.fail("ParseError expected")
    except parser.ParseError as e:
      self.assertRegexpMatches(e.message, re.escape(message))
      self.assertEquals(expected_line, e.line)


class ParserTest(_ParserTestBase):

  def test_syntax_error(self):
    self.check_error("123", 1, "syntax error")

  def test_constant(self):
    self.check("x = ...", "x = ...  # type: Any", "from typing import Any")
    self.check("x = ...  # type: str")
    self.check("x = 0", "x = ...  # type: int")
    self.check_error("\nx = 123", 2,
                     "Only '0' allowed as int literal")

  def test_alias_or_constant(self):
    self.check("x = True", "x = ...  # type: bool")
    self.check("x = False", "x = ...  # type: bool")
    self.check("x = Foo")

  def test_import(self):
    self.check("import foo.bar.baz", "")
    self.check_error("\n\nimport a as b", 3,
                     "Renaming of modules not supported")
    self.check("from foo.bar import baz")
    self.check("from foo.bar import baz as abc")
    self.check("from typing import NamedTuple, TypeVar", "")
    self.check("from foo.bar import *", "")
    self.check("from foo import a, b",
               "from foo import a\nfrom foo import b")
    self.check("from foo import (a, b)",
               "from foo import a\nfrom foo import b")
    self.check("from foo import (a, b, )",
               "from foo import a\nfrom foo import b")

  def test_duplicate_names(self):
    self.check_error("""\
      def foo() -> int: ...
      foo = ... # type: int""",
                     None,
                     "Duplicate top-level identifier(s): foo")
    self.check_error("""\
      from x import foo
      def foo() -> int: ...""",
                     None,
                     "Duplicate top-level identifier(s): foo")
    # A function is allowed to appear multiple times.
    self.check("""\
      def foo(x: int) -> int: ...
      def foo(x: str) -> str: ...""")

  def test_type(self):
    self.check("x = ...  # type: str")
    self.check("x = ...  # type: (str)", "x = ...  # type: str")
    self.check("x = ...  # type: foo.bar.Baz", prologue="import foo.bar")
    self.check("x = ...  # type: ?", "x = ...  # type: Any",
               prologue="from typing import Any")
    self.check("x = ...  # type: nothing")
    self.check("x = ...  # type: int or str or float", """\
                from typing import Union
                
                x = ...  # type: Union[int, str, float]""")

  def test_alias_lookup(self):
    self.check("""\
      from somewhere import Foo
      x = ...  # type: Foo
      """, """\
      import somewhere
      
      from somewhere import Foo
      
      x = ...  # type: somewhere.Foo""")


class HomogeneousTypeTest(_ParserTestBase):

  def test_strip_callable_parameters(self):
    self.check("import typing\n\nx = ...  # type: typing.Callable[int]",
               "import typing\n\nx = ...  # type: typing.Callable")

  def test_ellipsis(self):
    # B[T, ...] becomes B[T].
    self.check("x = ...  # type: List[int, ...]",
               "x = ...  # type: List[int]",
               prologue="from typing import List")
    # Double ellipsis is not allowed.
    self.check_error("x = ...  # type: List[..., ...]", 1,
                     "not supported")
    # Tuple[T] becomes Tuple[T, ...].
    self.check("from typing import Tuple\n\nx = ...  # type: Tuple[int]",
               "from typing import Tuple\n\nx = ...  # type: Tuple[int, ...]")

  def test_tuple(self):
    # Tuple[T, U] becomes Tuple[Union[T, U]
    self.check("""\
      from typing import Tuple, Union

      x = ...  # type: Tuple[int, str]""",
               """\
      from typing import Tuple, Union

      x = ...  # type: Tuple[Union[int, str], ...]""")

    # Tuple[T, U] becomes Tuple[Union[T, U]
    self.check("""\
      from typing import Tuple, Union

      x = ...  # type: Tuple[int, str, ...]""",
               """\
      from typing import Any, Tuple, Union

      x = ...  # type: Tuple[Union[int, str, Any], ...]""")

  def test_simple(self):
    self.check("x = ...  # type: Foo[int, str]")

  def test_implied_tuple(self):
    self.check("x = ...  # type: []",
               "x = ...  # type: Tuple[]",
               prologue="from typing import Tuple")
    self.check("x = ...  # type: [int]",
               "x = ...  # type: Tuple[int]",
               prologue="from typing import Tuple")
    self.check("x = ...  # type: [int, str]",
               "x = ...  # type: Tuple[int, str]",
               prologue="from typing import Tuple")


class NamedTupleTest(_ParserTestBase):

  def test_no_fields(self):
    self.check("x = ...  # type: NamedTuple(foo, [])", """\
      from typing import Any, Tuple

      x = ...  # type: `foo`

      class `foo`(Tuple[Any, ...]):
          pass
      """)

  def test_multiple_fields(self):
    expected = """\
      from typing import Tuple, Union

      x = ...  # type: `foo`

      class `foo`(Tuple[Union[int, str], ...]):
          a = ...  # type: int
          b = ...  # type: str
    """
    self.check("x = ...  # type: NamedTuple(foo, [(a, int), (b, str)])",
               expected)
    self.check("x = ...  # type: NamedTuple(foo, [(a, int), (b, str),])",
               expected)
    self.check("x = ...  # type: NamedTuple(foo, [(a, int,), (b, str),])",
               expected)

  def test_dedup_basename(self):
    self.check("""\
      x = ...  # type: NamedTuple(foo, [(a, int,)])
      y = ...  # type: NamedTuple(foo, [(b, str,)])""",
               """\
      from typing import Tuple

      x = ...  # type: `foo`
      y = ...  # type: `foo~1`

      class `foo`(Tuple[int, ...]):
          a = ...  # type: int

      class `foo~1`(Tuple[str, ...]):
          b = ...  # type: str
        """)


class FunctionTest(_ParserTestBase):

  def test_params(self):
    self.check("def foo() -> int: ...")
    self.check("def foo(x) -> int: ...")
    self.check("def foo(x: int) -> int: ...")
    self.check("def foo(x: int, y: str) -> int: ...")
    # Default values can add type information.
    self.check("def foo(x = 123) -> int: ...",
               "def foo(x: int = ...) -> int: ...")
    self.check("def foo(x = 12.3) -> int: ...",
               "def foo(x: float = ...) -> int: ...")
    self.check("def foo(x = None) -> int: ...",
               "def foo(x: None = ...) -> int: ...")
    self.check("def foo(x = xyz) -> int: ...",
               "def foo(x = ...) -> int: ...")
    self.check("def foo(x = ...) -> int: ...",
               "def foo(x = ...) -> int: ...")
    # Default of None will turn declared type into a union.
    self.check("def foo(x: str = None) -> int: ...",
               "def foo(x: Union[str, None] = ...) -> int: ...",
               prologue="from typing import Union")
    # Other defaults are ignored if a declared type is present.
    self.check("def foo(x: str = 123) -> int: ...",
               "def foo(x: str = ...) -> int: ...")

  def test_star_params(self):
    self.check("def foo(*, x) -> str: ...")
    self.check("def foo(x: int, *args) -> str: ...")
    self.check("def foo(x: int, *args: float) -> str: ...",
               prologue="from typing import Tuple")
    self.check("def foo(x: int, **kwargs) -> str: ...")
    self.check("def foo(x: int, **kwargs: float) -> str: ...",
               prologue="from typing import Dict")
    self.check("def foo(x: int, *args, **kwargs) -> str: ...")
    # Various illegal uses of * args.
    self.check_error("def foo(*) -> int: ...", 1,
                     "Named arguments must follow bare *")
    self.check_error("def foo(*x, *y) -> int: ...", 1,
                     "Unexpected second *")
    self.check_error("def foo(**x, *y) -> int: ...", 1,
                     "**x must be last parameter")

  def test_ellipsis_param(self):
    self.check("def foo(...) -> int: ...",
               "def foo(*args, **kwargs) -> int: ...")
    self.check("def foo(x: int, ...) -> int: ...",
               "def foo(x: int, *args, **kwargs) -> int: ...")
    self.check_error("def foo(..., x) -> int: ...", 1,
                     "ellipsis (...) must be last parameter")
    self.check_error("def foo(*, ...) -> int: ...", 1,
                     "ellipsis (...) not compatible with bare *")

  def test_decorators(self):
    # sense for methods of classes.  But this at least gives us some coverage
    # of the decorator logic.  More sensible tests can be created once classes
    # are implemented.
    self.check("""\
      @overload
      def foo() -> int: ...""",
               """\
      def foo() -> int: ...""")

    self.check("""\
      @abstractmethod
      def foo() -> int: ...""",
               """\
      def foo() -> int: ...""")

    self.check("""\
      @staticmethod
      def foo() -> int: ...""")

    self.check("""\
      @classmethod
      def foo() -> int: ...""")

    self.check_error("""\
      @property
      def foo(self) -> int""",
                     None,
                     "Module-level functions with property decorators: foo")

    self.check_error("""\
      @foo.setter
      def foo(self, x) -> int: ...""",
                     None,
                     "Module-level functions with property decorators: foo")

    self.check_error("""\
      @classmethod
      @staticmethod
      def foo() -> int: ...""",
                     3,
                     "Too many decorators for foo")

  def test_empty_body(self):
    self.check("def foo() -> int: ...")
    self.check("def foo() -> int",
               "def foo() -> int: ...")
    self.check("def foo() -> int: pass",
               "def foo() -> int: ...")
    self.check("""\
      def foo() -> int:
        ...""",
               """\
      def foo() -> int: ...""")
    self.check("""\
      def foo() -> int:
        pass""",
               """\
      def foo() -> int: ...""")
    self.check("""\
      def foo() -> int:
        '''doc string'''""",
               """\
      def foo() -> int: ...""")

  def test_body(self):
    # Mutators.
    self.check("""\
      def foo(x) -> int:
          x := int""")
    self.check_error("""\
      def foo(x) -> int:
          y := int""", 1, "No parameter named y")
    # Raise statements (currently ignored).
    self.check("""\
      def foo(x) -> int:
          raise Error""",
               """\
      def foo(x) -> int: ...""")
    self.check("""\
      def foo(x) -> int:
          raise Error()""",
               """\
      def foo(x) -> int: ...""")

  def test_return(self):
    self.check("def foo() -> int: ...")
    self.check("def foo(): ...",
               "def foo() -> Any: ...",
               prologue="from typing import Any")

  def test_raises(self):
    self.check("def foo() -> int raises RuntimeError: ...")
    self.check("def foo() -> int raises RuntimeError, TypeError: ...")

  def test_external_function(self):
    self.check("def foo PYTHONCODE")


class ClassTest(_ParserTestBase):

  def test_no_parents(self):
    canonical = """\
      class Foo:
          pass
      """

    self.check(canonical, canonical)
    self.check("""\
      class Foo():
          pass
      """, canonical)

  def test_parents(self):
    self.check("""\
      class Foo(Bar):
          pass
    """)
    self.check("""\
      class Foo(Bar, Baz):
          pass
      """)

  def test_parent_remove_nothingtype(self):
    self.check("""\
      class Foo(nothing):
          pass
      """, """\
      class Foo:
          pass
      """)
    self.check("""\
      class Foo(Bar, nothing):
          pass
      """, """\
      class Foo(Bar):
          pass
      """)

  def test_metaclass(self):
    self.check("""\
      class Foo(metaclass=Meta):
          pass
      """)
    self.check("""\
      class Foo(Bar, metaclass=Meta):
          pass
      """)
    self.check_error("""\
      class Foo(badkeyword=Meta):
          pass
      """, 1, "Only 'metaclass' allowed as classdef kwarg")
    self.check_error("""\
      class Foo(metaclass=Meta, Bar):
          pass
      """, 1, "metaclass must be last argument")

  def test_shadow_pep484(self):
    self.check("""\
      class List:
          def bar(self) -> List: ...
      """)

  def test_no_body(self):
    canonical = """\
      class Foo:
          pass
      """
    # There are numerous ways to indicate an empty body.
    self.check(canonical, canonical)
    self.check("""\
      class Foo(): pass
      """, canonical)
    self.check("""\
      class Foo(): ...
      """, canonical)
    self.check("""\
      class Foo():
          ...
      """, canonical)
    self.check("""\
      class Foo():
          ...
      """, canonical)
    # pylint: disable=g-inconsistent-quotes
    self.check('''\
      class Foo():
          """docstring"""
          ...
      ''', canonical)
    self.check('''\
      class Foo():
          """docstring"""
      ''', canonical)

  def test_attribute(self):
    self.check("""\
      class Foo:
          a = ...  # type: int
      """)

  def test_method(self):
    self.check("""\
      class Foo:
          def a(self, x: int) -> str: ...
      """)

  def test_property(self):
    self.check("""\
      class Foo:
          @property
          def a(self) -> int
      """, """\
      class Foo:
          a = ...  # type: int
      """)

  def test_duplicate_name(self):
    self.check_error("""\
      class Foo:
          bar = ...  # type: int
          bar = ...  # type: str
      """, 1, "Duplicate identifier(s): bar")
    self.check_error("""\
      class Foo:
          def bar(self) -> int: ...
          bar = ...  # type: str
      """, 1, "Duplicate identifier(s): bar")
    # Multiple method defs are ok (needed for variant signatures).
    self.check("""\
      class Foo:
          def x(self) -> int: ...
          def x(self) -> str: ...
      """)


class IfTest(_ParserTestBase):

  def test_if_true(self):
    self.check("""\
      if sys.version_info == (2, 7, 6):
        x = ...  # type: int
      """, """\
      x = ...  # type: int""")

  def test_if_false(self):
    self.check("""\
      if sys.version_info == (1, 2, 3):
        x = ...  # type: int
      """, "")

  def test_else_used(self):
    self.check("""\
      if sys.version_info == (1, 2, 3):
        x = ...  # type: int
      else:
        y = ...  # type: str
      """, """\
      y = ...  # type: str""")

  def test_else_ignored(self):
    self.check("""\
      if sys.version_info == (2, 7, 6):
        x = ...  # type: int
      else:
        y = ...  # type: str
      """, """\
      x = ...  # type: int""")

  def test_elif_used(self):
    self.check("""\
      if sys.version_info == (1, 2, 3):
        x = ...  # type: int
      elif sys.version_info == (2, 7, 6):
        y = ...  # type: float
      else:
        z = ...  # type: str
      """, """\
      y = ...  # type: float""")

  def test_elif_preempted(self):
    self.check("""\
      if sys.version_info > (1, 2, 3):
        x = ...  # type: int
      elif sys.version_info == (2, 7, 6):
        y = ...  # type: float
      else:
        z = ...  # type: str
      """, """\
      x = ...  # type: int""")

  def test_elif_ignored(self):
    self.check("""\
      if sys.version_info == (1, 2, 3):
        x = ...  # type: int
      elif sys.version_info == (4, 5, 6):
        y = ...  # type: float
      else:
        z = ...  # type: str
      """, """\
      z = ...  # type: str""")

  def test_nested_if(self):
    self.check("""\
      if sys.version_info >= (2, 0):
        if sys.platform == "linux":
          a = ...  # type: int
        else:
          b = ...  # type: int
      else:
        if sys.platform == "linux":
          c = ...  # type: int
        else:
          d = ...  # type: int
      """, "a = ...  # type: int")

  # The remaining tests verify that actions with side effects only take affect
  # within a true block.

  def test_conditional_import(self):
    self.check("""\
      if sys.version_info == (2, 7, 6):
        from foo import Processed
      else:
        from foo import Ignored
      """, "from foo import Processed")

  def test_conditional_alias_or_constant(self):
    self.check("""\
      if sys.version_info == (2, 7, 6):
        x = Processed
      else:
        y = Ignored
      """, "x = Processed")

  def test_conditional_class(self):
    self.check("""\
      if sys.version_info == (2, 7, 6):
        class Processed: pass
      else:
        class Ignored: pass
      """, """\
      class Processed:
          pass
      """)

  def test_conditional_class_registration(self):
    # There is a bug in legacy, so this cannot be checked against the legacy
    # parser.
    #
    # Class registration allows a local class name to shadow a PEP 484 name.
    # The only time this is noticeable is when the PEP 484 name is one of the
    # capitalized names that gets converted to lower case (i.e. List -> list).
    # In these cases a non-shadowed name would be converted to lower case, and
    # a properly shadowed name would remain capitalized.  In the test below,
    # Dict should be registered, List should not be registered.  Thus after
    # the "if" statement Dict refers to the local Dict class and List refers
    # to the PEP 484 list class.
    self.check("""\
      if sys.version_info == (2, 7, 6):
        class Dict: pass
      else:
        class List: pass

      x = ...  # type: Dict
      y = ...  # type: List
      """, """\
      x = ...  # type: Dict
      y = ...  # type: list

      class Dict:
          pass
      """, legacy=False)


class ConditionTest(_ParserTestBase):

  def check_cond(self, condition, expected):
    out = "x = ...  # type: int" if expected else ""
    self.check("""\
      if %s:
        x = ...  # type: int
      """ % condition, out)

  def check_cond_error(self, condition, message):
    self.check_error("""\
      if %s:
        x = ...  # type: int
      """ % condition, 1, message)

  def test_version_eq(self):
    self.check_cond("sys.version_info == (2, 7, 5)", False)
    self.check_cond("sys.version_info == (2, 7, 6)", True)
    self.check_cond("sys.version_info == (2, 7, 7)", False)

  def test_version_ne(self):
    self.check_cond("sys.version_info != (2, 7, 5)", True)
    self.check_cond("sys.version_info != (2, 7, 6)", False)
    self.check_cond("sys.version_info != (2, 7, 7)", True)

  def test_version_lt(self):
    self.check_cond("sys.version_info < (2, 7, 5)", False)
    self.check_cond("sys.version_info < (2, 7, 6)", False)
    self.check_cond("sys.version_info < (2, 7, 7)", True)
    self.check_cond("sys.version_info < (2, 8, 0)", True)

  def test_version_le(self):
    self.check_cond("sys.version_info <= (2, 7, 5)", False)
    self.check_cond("sys.version_info <= (2, 7, 6)", True)
    self.check_cond("sys.version_info <= (2, 7, 7)", True)
    self.check_cond("sys.version_info <= (2, 8, 0)", True)

  def test_version_gt(self):
    self.check_cond("sys.version_info > (2, 6, 0)", True)
    self.check_cond("sys.version_info > (2, 7, 5)", True)
    self.check_cond("sys.version_info > (2, 7, 6)", False)
    self.check_cond("sys.version_info > (2, 7, 7)", False)

  def test_version_ge(self):
    self.check_cond("sys.version_info >= (2, 6, 0)", True)
    self.check_cond("sys.version_info >= (2, 7, 5)", True)
    self.check_cond("sys.version_info >= (2, 7, 6)", True)
    self.check_cond("sys.version_info >= (2, 7, 7)", False)

  def test_version_shorter_tuples(self):
    self.check_cond("sys.version_info >= (2,)", True)
    self.check_cond("sys.version_info >= (3,)", False)
    self.check_cond("sys.version_info >= (2, 7)", True)
    self.check_cond("sys.version_info >= (2, 8)", False)

  def test_version_error(self):
    self.check_cond_error('sys.version_info == "foo"',
                          "sys.version_info must be compared to a tuple")
    self.check_cond_error("sys.version_info == (1.2, 3)",
                          "only integers are allowed in version tuples")

  def test_platform_eq(self):
    self.check_cond('sys.platform == "linux"', True)
    self.check_cond('sys.platform == "win32"', False)

  def test_platform_error(self):
    self.check_cond_error("sys.platform == (1, 2, 3)",
                          "sys.platform must be compared to a string")
    self.check_cond_error('sys.platform < "linux"',
                          "sys.platform must be compared using == or !=")
    self.check_cond_error('sys.platform <= "linux"',
                          "sys.platform must be compared using == or !=")
    self.check_cond_error('sys.platform > "linux"',
                          "sys.platform must be compared using == or !=")
    self.check_cond_error('sys.platform >= "linux"',
                          "sys.platform must be compared using == or !=")

  def test_unsupported_condition(self):
    self.check_cond_error("foo.bar == (1, 2, 3)",
                          "Unsupported condition: 'foo.bar'")


if __name__ == "__main__":
  unittest.main()