from functools import cache
from collections.abc import Collection


class Capybara:
    @classmethod
    @cache
    def hutia(cls) -> Collection[str]:
        return ()


class Gundi(Capybara):
    @classmethod
    def hutia(cls) -> Collection[str]:  # ty: ignore[invalid-attribute-override]
        return ()
