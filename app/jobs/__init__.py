import glob
import importlib.util
import sys
from os.path import basename, dirname, join

modules = glob.glob(join(dirname(__file__), "*.py"))

for file in modules:
    name = basename(file).replace('.py', '')
    if name.startswith('_'):
        continue

    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:
        continue
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
