import importlib.util
from pathlib import Path

path = Path(r'g:/My Drive/Scripts/CloudFunctions/shr_people/main.py')
spec = importlib.util.spec_from_file_location('shr_people_main', path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

for value in ['Branco,Patricia,', 'Cheung,Dorothy,WS', 'Smith,John', '']:
    print(f'{value!r} -> {mod.clean_rsm_name(value)!r}')
