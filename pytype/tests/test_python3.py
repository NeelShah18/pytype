"""Python 3 tests for Byterun."""


from pytype import utils
from pytype.tests import test_base


class TestPython3(test_base.BaseTest):
  """Tests for Python 3 compatiblity."""

  PYTHON_VERSION = (3, 4)

  def test_make_function(self):
    src = """
      def uses_annotations(x: int) -> int:
        i, j = 3, 4
        return i

      def uses_pos_defaults(x, y=1):
        i, j = 3, 4
        return __any_object__

      def uses_kw_defaults(x, *myargs, y=1):
        i, j = 3, 4
        return __any_object__

      def uses_kwargs(x, **mykwargs):
        i, j = 3, 4
        return __any_object__
    """
    output = """
      def uses_annotations(x: int) -> int
      def uses_pos_defaults(x, y=...) -> ?
      def uses_kw_defaults(x, *myargs, y=...) -> ?
      def uses_kwargs(x, **mykwargs) -> ?
    """
    self.assertTypesMatchPytd(
        self.Infer(src, deep=False), output)
    self.assertTypesMatchPytd(
        self.Infer(src, deep=True), output)

  def test_make_function2(self):
    ty = self.Infer("""
      def f(x, *myargs, y):
        return __any_object__
    """)
    self.assertTypesMatchPytd(ty, """
      def f(x, *myargs, y) -> ?
    """)

  def test_defaults(self):
    ty = self.Infer("""
      def foo(a, b, c, d=0, e=0, f=0, g=0, *myargs,
              u, v, x, y=0, z=0, **mykwargs):
        return 3
    """, deep=False)
    self.assertTypesMatchPytd(ty, """
      def foo(a, b, c, d=..., e=..., f=..., g=..., *myargs,
              u, v, x, y=..., z=..., **mykwargs)
    """)

  def test_defaults_and_annotations(self):
    ty = self.Infer("""
      def foo(a, b, c:int, d=0, e=0, f=0, g=0, *myargs,
              u:str, v, x:float=0, y=0, z=0, **mykwargs):
        return 3
    """, deep=False)
    self.assertTypesMatchPytd(ty, """
      def foo(a, b, c:int, d=..., e=..., f=..., g=..., *myargs,
              u:str, v, x:float=..., y=..., z=..., **mykwargs)
    """)

  def test_make_class(self):
    ty = self.Infer("""
      class Thing(tuple):
        def __init__(self, x):
          self.x = x
      def f():
        x = Thing(1)
        x.y = 3
        return x
    """)

    self.assertTypesMatchPytd(ty, """
    from typing import Any
    class Thing(tuple):
      x = ...  # type: Any
      y = ...  # type: int
      def __init__(self, x) -> NoneType: ...
    def f() -> Thing: ...
    """)

  def test_class_kwargs(self):
    ty = self.Infer("""
      # x, y are passed to type() or the metaclass. We currently ignore them.
      class Thing(x=True, y="foo"): pass
    """)
    self.assertTypesMatchPytd(ty, """
    class Thing: ...
    """)

  def test_exceptions(self):
    ty = self.Infer("""
      def f():
        try:
          raise ValueError()  # exercise byte_RAISE_VARARGS
        except ValueError as e:
          x = "s"
        finally:  # exercise byte_POP_EXCEPT
          x = 3
        return x
    """)
    self.assertTypesMatchPytd(ty, """
      def f() -> int
    """)

  def test_byte_unpack_ex(self):
    ty = self.Infer("""
      from typing import List
      a, *b, c, d = 1, 2, 3, 4, 5, 6, 7
      e, f, *g, h = "hello world"
      i, *j = 1, 2, 3, "4"
      *k, l = 4, 5, 6
      m, *n, o = [4, 5, "6", None, 7, 8]
      p, *q, r = 4, 5, "6", None, 7, 8
      vars = None # type : List[int]
      s, *t, u = vars
    """)
    self.assertTypesMatchPytd(ty, """
      from typing import List, Optional, Union
      a = ... # type: int
      b = ... # type: List[int]
      c = ... # type: int
      d = ... # type: int
      e = ... # type: str
      f = ... # type: str
      g = ... # type: List[str]
      h = ... # type: str
      i = ... # type: int
      j = ... # type: List[Union[int, str]]
      k = ... # type: List[int]
      l = ... # type: int
      m = ... # type: int
      n = ... # type: List[Optional[Union[int, str]]]
      o = ... # type: int
      p = ... # type: int
      q = ... # type: List[Optional[Union[int, str]]]
      r = ... # type: int
      s = ...  # type: int
      t = ...  # type: List[int]
      u = ...  # type: int
      vars = ...  # type: List[int]
    """)

  def test_metaclass_kwarg(self):
    self.Check("""
      import abc
      class Example(metaclass=abc.ABCMeta):
        @abc.abstractmethod
        def foo(self) -> int:
          return None
    """)

  def test_bytearray_slice(self):
    self.Check("""
      def f(x: bytearray) -> bytearray:
        return x[1:]
      def g(x: bytearray) -> bytearray:
        return x[1:5:2]
    """)

  def test_builtins(self):
    self.Check("""
      import builtins
    """)

  def test_unicode(self):
    errors = self.CheckWithErrors("""\
      unicode("foo")
    """)
    self.assertErrorLogIs(errors, [(1, "name-error")])

  def test_bytes_iteration(self):
    errors = self.CheckWithErrors("""\
      def f():
        for x in bytes():
          return bytes() + x
    """)
    self.assertErrorLogIs(errors, [(3, "wrong-arg-types")])

  def test_exec_builtin(self):
    with utils.Tempdir() as d:
      d.create_file("foo.pyi", """
        x = exec
      """)
      self.Check("""\
        import foo
        foo.x("a = 2")
      """, pythonpath=[d.path])

  def test_raise_exception_from(self):
    self.Check("raise ValueError from NameError")

  def test_inplace_division(self):
    self.Check("""\
      x, y = 24, 3
      x /= y
      assert x == 8.0 and y == 3
      assert isinstance(x, float)
      x /= y
      assert x == (8.0/3.0) and y == 3
      assert isinstance(x, float)
    """)

  def test_removed_dict_methods(self):
    errors = self.CheckWithErrors("""\
      {}.iteritems
      {}.iterkeys
      {}.itervalues
      {}.viewitems
      {}.viewkeys
      {}.viewvalues
    """)
    self.assertErrorLogIs(
        errors, [(1, "attribute-error"), (2, "attribute-error"),
                 (3, "attribute-error"), (4, "attribute-error"),
                 (5, "attribute-error"), (6, "attribute-error")])

  def test_dict_views(self):
    self.Check("""
      from typing import KeysView, ItemsView, ValuesView
      def f(x: KeysView): ...
      def g(x: ItemsView): ...
      def h(x: ValuesView): ...
      f({}.keys())
      g({}.items())
      h({}.values())
    """)

  def test_load_classderef(self):
    """Exercises the LOAD_CLASSDEREF opcode."""
    self.Check("""
      class A(object):
        def foo(self):
          x = 10
          class B(object):
            y = str(x)
    """)


if __name__ == "__main__":
  test_base.main()
