from collections.abc import Callable


class Base:
    f: Callable[[int], int]


class Child(Base):
    def f(self) -> int:  # ty: ignore[invalid-attribute-override]
        return 0
