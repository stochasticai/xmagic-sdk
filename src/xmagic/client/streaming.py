"""Streams you can close.

A streaming call used to return a bare generator. That works until the caller
stops early: breaking out of ``for event in client.chats.stream(...)`` leaves
the generator suspended inside its ``with connect_sse(...)`` block, and the HTTP
response stays open until the garbage collector gets to it. On CPython that is
usually soon; for an async generator it is whenever the event loop's finalizer
runs, which may be never. Either way, nothing in the type said the stream
*could* be closed.

:class:`Stream` and :class:`AsyncStream` wrap the generator so it can. They are
still iterators, so every existing ``for`` loop is unchanged; they add
``close()`` / ``aclose()``, which is also how an in-flight query is cancelled,
and they are context managers so the close is written once, at the top, and
runs whichever way the loop ends.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import Generic, TypeVar

T = TypeVar("T")


class Stream(Generic[T]):
    """An iterator over streamed items with a deterministic ``close()``.

    Closing raises ``GeneratorExit`` at the generator's suspended ``yield``,
    which unwinds its ``with`` block and closes the HTTP response right then.
    It is idempotent, and iterating a closed stream yields nothing more.
    """

    def __init__(self, source: Iterator[T]) -> None:
        self._source = source
        self.closed = False

    def __iter__(self) -> Stream[T]:
        return self

    def __next__(self) -> T:
        if self.closed:
            raise StopIteration
        try:
            return next(self._source)
        except StopIteration:
            self.closed = True
            raise

    def close(self) -> None:
        """Stop the stream and release its connection now, not at GC."""
        if self.closed:
            return
        self.closed = True
        close = getattr(self._source, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> Stream[T]:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class AsyncStream(Generic[T]):
    """Async mirror of :class:`Stream`; ``aclose()`` is awaited, so it is certain.

    This is the one that matters most: an async generator dropped mid-iteration
    is finalized by the event loop's ``asyncgen`` hooks, on a schedule the
    caller does not control -- and not at all once the loop is gone.
    """

    def __init__(self, source: AsyncIterator[T]) -> None:
        self._source = source
        self.closed = False

    def __aiter__(self) -> AsyncStream[T]:
        return self

    async def __anext__(self) -> T:
        if self.closed:
            raise StopAsyncIteration
        try:
            return await self._source.__anext__()
        except StopAsyncIteration:
            self.closed = True
            raise

    async def aclose(self) -> None:
        """Stop the stream and release its connection now, not whenever."""
        if self.closed:
            return
        self.closed = True
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            await aclose()

    async def __aenter__(self) -> AsyncStream[T]:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
