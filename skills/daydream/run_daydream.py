import os
import sys

_root = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
for _candidate in (_root, os.path.join(_root, 'scripts'), os.path.join(_root, '..', 'scripts')):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from daydream import run as _run_daydream

_context = globals().get('context')
if _context is None:
    print('This step expects an npcsh jinx context. Standalone CLI: python scripts/daydream.py --help')
else:
    _context['output'] = _run_daydream(_context)
