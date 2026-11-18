"""Small, UI-independent rules for the desktop companion."""

import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path


REWARD_INTERVALS = {'candy': 15 * 60, 'burger': 2 * 3600, 'cake': 5 * 3600}


def number(value, default=0.0, minimum=0.0, maximum=float('inf')):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, result)) if math.isfinite(result) else default


def normalize_data(data, now):
    if not isinstance(data, dict):
        raise ValueError('Save data must be an object')
    saved_at = number(data.get('last_save_time'), now)
    legacy_start = number(data.get('work_start_time'))
    legacy_session = max(0, saved_at - legacy_start) if data.get('working') and legacy_start > 0 else 0
    session = number(data.get('work_session_seconds'), legacy_session)
    total = number(data.get('work_total_seconds'), session)
    raw_marks = data.get('reward_marks', {})
    if not isinstance(raw_marks, dict):
        raw_marks = {}
    todos = []
    raw_todos = data.get('todo_list', [])
    for index, item in enumerate(raw_todos if isinstance(raw_todos, list) else []):
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            continue
        item = dict(item)
        item.setdefault('id', f'legacy-{index}')
        item['completed'] = bool(item.get('completed', False))
        # Completed legacy items may already have paid out.
        item.setdefault('reward_claimed', item['completed'])
        if not number(item.get('due_at')):
            try:
                hour, minute = map(int, item.get('target_time', '').split(':'))
                # Legacy HH:mm entries belong to the last saved day, never silently tomorrow.
                item['due_at'] = datetime.fromtimestamp(saved_at).replace(
                    hour=hour, minute=minute, second=59, microsecond=0).timestamp()
            except (ValueError, TypeError, AttributeError, OSError, OverflowError):
                item['due_at'] = 0
        else:
            item['due_at'] = number(item['due_at'], maximum=4102444799)
        todos.append(item)
    # Offline sleep is gentle: at most 20 satiety points lost per absence.
    offline_decay = min(20.0, max(0, now - saved_at) * 2 / 3600)
    position = data.get('position')
    if not (isinstance(position, list) and len(position) == 2
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in position)):
        position = None
    return {
        'satiety': max(0, number(data.get('satiety'), 100, maximum=100) - offline_decay),
        **{f'{key}_count': int(number(data.get(f'{key}_count'), maximum=1000000))
           for key in REWARD_INTERVALS},
        'todo_list': todos,
        'affection': number(data.get('affection'), maximum=100),
        'quiet_mode': data.get('quiet_mode') is True,
        'last_snack_date': data.get('last_snack_date') if isinstance(data.get('last_snack_date'), str) else '',
        'working': data.get('working') is True,
        'work_session_seconds': session,
        'work_total_seconds': total,
        'reward_marks': {key: int(number(raw_marks.get(key), total // interval,
                                         maximum=total // interval))
                         for key, interval in REWARD_INTERVALS.items()},
        'pet_size': int(number(data.get('pet_size'), 200, 80, 400)),
        'position': position,
    }


def read_save(path, legacy_path, now):
    """Try the user save, its backup, then the original portable save."""
    errors = []
    for candidate in dict.fromkeys([Path(path), Path(str(path) + '.bak'), Path(legacy_path)]):
        if not candidate.exists():
            continue
        try:
            with candidate.open(encoding='utf-8') as handle:
                return normalize_data(json.load(handle), now), errors
        except (OSError, ValueError, TypeError) as error:
            errors.append(f'{candidate}: {error}')
    return normalize_data({}, now), errors


def _replace_file(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def write_save(path, data):
    """Preserve the previous valid document before atomically replacing it."""
    path = Path(path)
    if path.exists():
        try:
            previous = path.read_text(encoding='utf-8')
            if isinstance(json.loads(previous), dict):
                _replace_file(str(path) + '.bak', previous)
        except (ValueError, UnicodeError):
            pass
    _replace_file(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


def behavior_weights(satiety, affection, working, recent):
    """Contextual variety with a cooldown for the most recent action."""
    weights = {'idle': 5, 'look': 2, 'wave': 1 + affection / 40,
               'sleep': 1, 'dance': 1, 'bounce': 1, 'chase': 1, 'wander': 4}
    if satiety < 25:
        weights.update(sleep=5, dance=0, bounce=0, chase=0, wander=1)
    if working:
        weights.update(idle=12, look=2, sleep=2, dance=0, bounce=0, chase=0, wander=0)
    if recent in weights:
        weights[recent] *= 0.15
    return weights
