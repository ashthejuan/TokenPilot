#!/usr/bin/env python3
"""Seed demo sessions by driving real gateway chat completions.

Never bulk-inserts into ``/usage/events``. Produces:

* a debugging session with a large prompt resent each turn plus two
  ``429 → retry`` sequences (detectors B + C);
* an expensive session marked ``failure`` (detector D);
* a cheap successful control session.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import httpx

EVENT_ID_HEADER = "X-TokenPilot-Event-Id"
DEFAULT_API = "http://127.0.0.1:8787"
# Shared large block (≥ context_min_chars) so detector C hashes match across turns.
FULL_REPO_PAD = (
    "Repository files (full_repo context):\n"
    + ("=== invoicing/discounts.py ===\n" + ("# pad line for repeated context\n" * 80) + "\n")
    + ("=== invoicing/totals.py ===\n" + ("# more fixture context\n" * 80) + "\n")
    + ("=== tests/test_discounts.py ===\n" + ("# test pad\n" * 40) + "\n")
)


def _api_base() -> str:
    return os.environ.get("TOKENPILOT_API_URL", DEFAULT_API).rstrip("/")


def _token() -> str:
    token = os.environ.get("TOKENPILOT_LOCAL_TOKEN", "").strip()
    if not token:
        raise SystemExit("TOKENPILOT_LOCAL_TOKEN must be set")
    return token


def _model(mode: str, *, expensive: bool = False) -> str:
    if mode == "offline":
        return "fake-large" if expensive else "fake-small"
    return "muse-spark-1.3"


def _headers(project: str, session: str, task: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "X-TokenPilot-Project": project,
        "X-TokenPilot-Session": session,
    }
    if task:
        headers["X-TokenPilot-Task"] = task
    return headers


def _chat(
    client: httpx.Client,
    *,
    project: str,
    session: str,
    model: str,
    content: str,
    task: str | None = None,
    retry_of: str | None = None,
    fake_behavior: str | None = None,
) -> httpx.Response:
    headers = _headers(project, session, task)
    if retry_of:
        headers["X-TokenPilot-Retry-Of"] = retry_of
    if fake_behavior:
        headers["X-Fake-Behavior"] = fake_behavior
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": content},
        ],
        "stream": False,
    }
    return client.post(f"{_api_base()}/gateway/v1/chat/completions", json=body, headers=headers)


def _require_event_id(response: httpx.Response) -> str:
    event_id = response.headers.get(EVENT_ID_HEADER)
    if not event_id:
        raise RuntimeError(
            f"missing {EVENT_ID_HEADER} on gateway response "
            f"(status={response.status_code})"
        )
    return event_id


def _find_session_id(client: httpx.Client, project_slug: str, external: str) -> str:
    auth = {"Authorization": f"Bearer {_token()}"}
    projects = client.get(f"{_api_base()}/api/v1/projects", headers=auth)
    projects.raise_for_status()
    project_id = next(
        (
            p["id"]
            for p in projects.json()
            if p.get("slug") == project_slug or p.get("name") == project_slug
        ),
        None,
    )
    params: dict[str, Any] = {"limit": 100}
    if project_id:
        params["project_id"] = project_id
    listed = client.get(f"{_api_base()}/api/v1/sessions", headers=auth, params=params)
    listed.raise_for_status()
    for item in listed.json().get("items", []):
        if item.get("external_session_id") == external:
            return str(item["id"])
    raise RuntimeError(f"session with external id {external!r} not found after seeding")


def seed_debugging(client: httpx.Client, *, mode: str, project: str) -> str:
    """Large prompt resent each turn + two 429→retry sequences."""
    session = "demo-debug-1"
    model = _model(mode, expensive=True) if mode == "offline" else _model(mode)
    # Offline debugging uses fake-large so Simulated pricing applies.
    if mode == "offline":
        model = "fake-large"
    prompt = (
        "Debug the discount-before-tax bug. Keep the full repository in context.\n\n"
        + FULL_REPO_PAD
    )
    assert len(prompt) >= 2000

    # Turn 1: success with full context.
    r1 = _chat(client, project=project, session=session, model=model, content=prompt, task="debug")
    if r1.status_code >= 400:
        raise RuntimeError(f"debug turn1 failed: {r1.status_code} {r1.text[:200]}")
    _require_event_id(r1)

    # Two 429 → retry sequences. Offline forces 429 via X-Fake-Behavior;
    # live Meta rarely rate-limits, so we still send Retry-Of against the
    # prior event id to form explicit retry groups for detector B.
    for _ in range(2):
        time.sleep(0.05)
        first = _chat(
            client,
            project=project,
            session=session,
            model=model,
            content=prompt,
            task="debug",
            fake_behavior="error" if mode == "offline" else None,
        )
        if mode == "offline" and first.status_code != 429:
            raise RuntimeError(
                f"expected offline 429, got {first.status_code}: {first.text[:200]}"
            )
        if mode == "live" and first.status_code >= 500:
            raise RuntimeError(f"debug live attempt failed: {first.status_code}")
        parent = _require_event_id(first)
        time.sleep(0.05)
        retry = _chat(
            client,
            project=project,
            session=session,
            model=model,
            content=prompt,
            task="debug",
            retry_of=parent,
        )
        if retry.status_code >= 400:
            raise RuntimeError(f"debug retry failed: {retry.status_code} {retry.text[:200]}")
        _require_event_id(retry)

    # One more identical turn so repeated_context clears min occurrences (3).
    time.sleep(0.05)
    r_final = _chat(
        client, project=project, session=session, model=model, content=prompt, task="debug"
    )
    if r_final.status_code >= 400:
        raise RuntimeError(f"debug final turn failed: {r_final.status_code}")
    _require_event_id(r_final)
    return session


def seed_expensive_failed(client: httpx.Client, *, mode: str, project: str) -> str:
    session = "demo-expensive-fail"
    model = "fake-large" if mode == "offline" else _model(mode)
    # Mid-size prompt → fake returns 200k prompt tokens (~$0.60) offline.
    content = (
        "Attempt an expensive refactor of the invoicing package.\n"
        + ("Consider every module carefully.\n" * 200)
    )
    r = _chat(
        client,
        project=project,
        session=session,
        model=model,
        content=content,
        task="expensive-refactor",
    )
    if r.status_code >= 400:
        raise RuntimeError(f"expensive seed failed: {r.status_code} {r.text[:200]}")
    _require_event_id(r)

    # Second call so live costs more reliably clear unsuccessful_min_cost.
    time.sleep(0.05)
    r2 = _chat(
        client,
        project=project,
        session=session,
        model=model,
        content=content + "\nContinue.\n",
        task="expensive-refactor",
    )
    if r2.status_code >= 400:
        raise RuntimeError(f"expensive seed turn2 failed: {r2.status_code}")
    _require_event_id(r2)

    session_id = _find_session_id(client, project, session)
    # API SessionOutcome is ``failure`` (not ``failed``).
    patch = client.patch(
        f"{_api_base()}/api/v1/sessions/{session_id}",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json={"outcome": "failure"},
    )
    if patch.status_code >= 400:
        raise RuntimeError(f"session outcome patch failed: {patch.status_code} {patch.text[:200]}")
    return session


def seed_cheap_success(client: httpx.Client, *, mode: str, project: str) -> str:
    session = "demo-cheap-ok"
    model = "fake-small" if mode == "offline" else _model(mode)
    r = _chat(
        client,
        project=project,
        session=session,
        model=model,
        content="Say ok.",
        task="cheap-control",
    )
    if r.status_code >= 400:
        raise RuntimeError(f"cheap seed failed: {r.status_code} {r.text[:200]}")
    _require_event_id(r)
    session_id = _find_session_id(client, project, session)
    patch = client.patch(
        f"{_api_base()}/api/v1/sessions/{session_id}",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json={"outcome": "success"},
    )
    if patch.status_code >= 400:
        raise RuntimeError(f"cheap outcome patch failed: {patch.status_code} {patch.text[:200]}")
    return session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "offline"), required=True)
    parser.add_argument("--project", default="invoicing-demo")
    args = parser.parse_args(argv)

    with httpx.Client(timeout=120.0) as client:
        debug = seed_debugging(client, mode=args.mode, project=args.project)
        expensive = seed_expensive_failed(client, mode=args.mode, project=args.project)
        cheap = seed_cheap_success(client, mode=args.mode, project=args.project)

    print(f"seeded sessions: debug={debug} expensive={expensive} cheap={cheap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
