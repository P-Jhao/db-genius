"""Bounded real stale-task bursts, with observed locale reset on every required channel."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic, sleep
from typing import TYPE_CHECKING

from test_s14_runtime_support import Runtime, obj

if TYPE_CHECKING:
    from test_s14_runtime_tracing import Record, WireSpan

_PUBLISH = """
import json, sys
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import User, DbConfig
from app.tasks.db_config import verify_config
batch = json.loads(sys.argv[2])
identifiers = {item['id'] for item in batch}
with SessionLocal() as session:
    owned = {config.id: config for config in session.scalars(
        select(DbConfig).join(User, User.id == DbConfig.user_id).where(
            User.username == sys.argv[1], DbConfig.id.in_(identifiers)))}
    if set(owned) != identifiers or any(config.status != 1 or config.verification_version <= 0
                                      for config in owned.values()):
        raise RuntimeError('Exact fresh owned verification configs required')
    for item in batch:
        config = owned[item['id']]
        verify_config.apply_async(args=(config.id, config.verification_version - 1), headers=item['headers'])
print(json.dumps({'published': len(batch)}))
"""
_WAVES = 4


@dataclass(repr=False)
class ResetEvidence:
    records: list[Record] = field(repr=False)
    payload: bytes = field(repr=False)
    default_ids: set[bytes] = field(repr=False)
    reset_channels: set[int] = field(repr=False)
    callbacks: int
    waves: int


def cover_reset_channels(
    runtime: Runtime, identifiers: list[int], localized: list[Record], sentinel: str,
    snapshot: Callable[[], tuple[list[Record], bytes]],
    attributes: Callable[[WireSpan], dict[str, str]],
    headers_for: Callable[[str], tuple[bytes, dict[str, str]]],
) -> ResetEvidence:
    # Keep the original 60-second reset budget; count all publishing and polling.
    deadline = monotonic() + 60
    batch_size = runtime.processes * 2
    maximum = batch_size * _WAVES
    if len(identifiers) != 2 or len(set(identifiers)) != 2 or len(localized) != 2 or batch_size < 2:
        raise ValueError('Two completed localized configs and a real bounded pool required')
    latest_end = {record.channel: max(item.span.end_time_unix_nano for item in localized
                                     if item.channel == record.channel) for record in localized}
    required = set(latest_end)
    before = runtime.metric('sqlchat_verifications_total', outcome='stale')
    default_ids: set[bytes] = set()
    reset_channels: set[int] = set()
    observed: set[bytes] = set()
    records: list[Record] = []
    payload = b''
    waves = 0
    delta = 0.0
    progress = runtime.report_dir / 'trace_reset_progress.json'
    progress.open('x', encoding='utf-8').close()

    def receipt(*, passed: bool = False, exhausted: bool = False) -> None:
        values = {'passed': passed, 'budget_seconds': 60, 'maximum_callbacks': maximum,
                  'callbacks_published': len(default_ids), 'publish_waves': waves,
                  'own_default_worker_traces': len(observed), 'stale_delta': delta,
                  'required_localized_channels': len(required), 'covered_localized_channels': len(reset_channels),
                  'coverage_complete': reset_channels == required, 'task_cap_reached': len(default_ids) == maximum,
                  'callback_bound_exhausted': exhausted,
                  'all_sent_defaults_exported': observed == default_ids}
        temporary = progress.with_suffix('.tmp')
        temporary.write_text(json.dumps(values, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        temporary.replace(progress)

    receipt()
    while True:
        if monotonic() >= deadline:
            receipt()
            raise TimeoutError('Bounded real default callbacks did not cover every localized exporter channel')
        # A new burst is allowed only after the preceding burst is fully completed
        # and all its exact trace IDs are exported. Never assume fair prefork routing.
        if waves == 0 or observed == default_ids and delta == len(default_ids) and reset_channels != required:
            if waves >= _WAVES:
                receipt(exhausted=True)
                raise TimeoutError('Real default callback bound exhausted before same-channel reset coverage')
            pairs = [headers_for(sentinel) for _ in range(batch_size)]
            next_ids = {identifier for identifier, _ in pairs}
            if len(next_ids) != batch_size or next_ids & default_ids:
                raise RuntimeError('Fresh callback trace identities required')
            batch = [{'id': identifiers[index % 2], 'headers': headers}
                     for index, (_, headers) in enumerate(pairs)]
            if monotonic() >= deadline:
                receipt()
                raise TimeoutError('No callback burst may begin after the original reset budget')
            packet = obj(json.loads(runtime.script(_PUBLISH, runtime.session.username, json.dumps(batch))))
            if packet.get('published') != batch_size:
                raise RuntimeError('Actual owned callback burst was not fully published')
            default_ids.update(next_ids)
            waves += 1
            receipt()
        delta = runtime.metric('sqlchat_verifications_total', outcome='stale') - before
        receipt()
        if delta < 0 or delta > len(default_ids):
            raise RuntimeError('Exclusive real stale counter window was changed')
        records, payload = snapshot()
        observed = set()
        reset_channels = set()
        for record in records:
            if record.span.trace_id not in default_ids or record.span.name != 'celery.db_config.verify':
                continue
            fields = attributes(record.span)
            if (fields.get('chat.locale') != 'en' or fields.get('outcome') != 'stale'
                    or record.resource != {'service.name': 'sqlchat-worker'}):
                raise AssertionError('Actual no-locale callback must use default en and fixed worker resource')
            observed.add(record.span.trace_id)
            if record.channel in required and record.span.start_time_unix_nano > latest_end[record.channel]:
                reset_channels.add(record.channel)
        receipt()
        if monotonic() >= deadline:
            raise TimeoutError('Reset observation exceeded the original time budget')
        if reset_channels == required and observed == default_ids and delta == len(default_ids):
            receipt(passed=True)
            return ResetEvidence(records, payload, default_ids, reset_channels, len(default_ids), waves)
        sleep(0.2)
