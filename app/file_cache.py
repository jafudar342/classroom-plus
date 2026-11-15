"""Bounded read-through caches that follow atomic replacements and external edits."""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock


def fingerprint(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class FileCache:
    def __init__(self, capacity=128):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.lock = RLock()

    def get(self, paths, load):
        paths = tuple(paths)
        signature = tuple(fingerprint(path) for path in paths)
        with self.lock:
            entry = self.entries.get(paths)
            if entry is not None and entry[0] == signature:
                self.entries.move_to_end(paths)
                return deepcopy(entry[1])
        value = load()
        # Never retain a value assembled while its source files were changing.
        try:
            stable = tuple(fingerprint(path) for path in paths) == signature
        except OSError:
            stable = False
        if stable:
            with self.lock:
                self.entries[paths] = (signature, deepcopy(value))
                self.entries.move_to_end(paths)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
        return value
