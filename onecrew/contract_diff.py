"""One lossless contract comparison for report and resume-pack readers."""
import copy

GONE = object()


def diff(old, new, path='', *, missing=GONE):
    """Report's original tuple API, including order changes and full values."""
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            where = f'{path}.{key}' if path else key
            if key not in old: out.append((where, 'thêm', missing, new[key]))
            elif key not in new: out.append((where, 'bỏ', old[key], missing))
            else: out += diff(old[key], new[key], where, missing=missing)
    elif isinstance(old, list) and isinstance(new, list):
        if old == new: return out
        if (old or new) and all(isinstance(x, dict) and 'id' in x for x in old + new):
            before, after = {x['id']: x for x in old}, {x['id']: x for x in new}
            for key in list(before) + [k for k in after if k not in before]:
                where = f'{path}[{key}]'
                if key not in before: out.append((where, 'thêm', missing, after[key]))
                elif key not in after: out.append((where, 'bỏ', before[key], missing))
                else: out += diff(before[key], after[key], where, missing=missing)
            if [x['id'] for x in old if x['id'] in after] != [x['id'] for x in new if x['id'] in before]:
                out.append((path, 'đổi thứ tự', old, new))
        else:
            gone, came = [x for x in old if x not in new], [x for x in new if x not in old]
            out += [(path, 'bỏ', x, missing) for x in gone] + [(path, 'thêm', missing, x) for x in came]
            if not gone and not came: out.append((path, 'đổi thứ tự', old, new))
    elif old != new:
        out.append((path, 'đổi', old, new))
    return out


def changes(old, new):
    labels = {'thêm': 'added', 'bỏ': 'removed', 'đổi': 'changed', 'đổi thứ tự': 'reordered'}
    return [{'path': path, 'change': labels[how], 'before': None if before is GONE else copy.deepcopy(before),
             'after': None if after is GONE else copy.deepcopy(after)} for path, how, before, after in diff(old, new)]
