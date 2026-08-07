"""Narrow functional port for the deterministic resource coordinator.

The domain implementation remains ordinary pure functions in
``lakatos.resource_coordination``.  This module packages those functions as an
immutable capability so imperative adapters can depend on a tiny protocol and
tests can replace the capability without patching module globals.

A compatible implementation must preserve the persisted schema and engine-rule
identity.  Supplying a kernel is explicit authority; the journal never discovers
one from ambient configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from lakatos.resource_coordination import (
    Decision,
    ENGINE_RULE_SHA256,
    ResourceCommand,
    ResourceState,
    ResourceTransition,
    SCHEMA_VERSION,
    decide,
    evolve,
)


class ResourceKernel(Protocol):
    """Behavioral port consumed by durable resource-state adapters."""

    schema_version: str
    engine_rule_sha256: str

    def decide(self, state: ResourceState, command: ResourceCommand) -> Decision:
        ...

    def evolve(
        self,
        state: ResourceState,
        transition: ResourceTransition,
    ) -> ResourceState:
        ...


@dataclass(frozen=True, slots=True)
class FunctionalResourceKernel:
    """Immutable bundle of referentially transparent resource functions."""

    decide_fn: Callable[[ResourceState, ResourceCommand], Decision] = field(
        default=decide,
        repr=False,
    )
    evolve_fn: Callable[[ResourceState, ResourceTransition], ResourceState] = field(
        default=evolve,
        repr=False,
    )
    schema_version: str = SCHEMA_VERSION
    engine_rule_sha256: str = ENGINE_RULE_SHA256

    def __post_init__(self) -> None:
        if not callable(self.decide_fn) or not callable(self.evolve_fn):
            raise TypeError("resource kernel functions must be callable")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("resource kernel schema is incompatible")
        if self.engine_rule_sha256 != ENGINE_RULE_SHA256:
            raise ValueError("resource kernel rule identity is incompatible")

    def decide(self, state: ResourceState, command: ResourceCommand) -> Decision:
        return self.decide_fn(state, command)

    def evolve(
        self,
        state: ResourceState,
        transition: ResourceTransition,
    ) -> ResourceState:
        return self.evolve_fn(state, transition)


def require_compatible_resource_kernel(kernel: ResourceKernel) -> ResourceKernel:
    """Fail closed before an adapter accepts an incompatible kernel capability."""

    if getattr(kernel, "schema_version", None) != SCHEMA_VERSION:
        raise ValueError("resource kernel schema is incompatible")
    if getattr(kernel, "engine_rule_sha256", None) != ENGINE_RULE_SHA256:
        raise ValueError("resource kernel rule identity is incompatible")
    if not callable(getattr(kernel, "decide", None)):
        raise TypeError("resource kernel decide port must be callable")
    if not callable(getattr(kernel, "evolve", None)):
        raise TypeError("resource kernel evolve port must be callable")
    return kernel


DEFAULT_RESOURCE_KERNEL = FunctionalResourceKernel()


__all__ = [
    "DEFAULT_RESOURCE_KERNEL",
    "FunctionalResourceKernel",
    "ResourceKernel",
    "require_compatible_resource_kernel",
]
