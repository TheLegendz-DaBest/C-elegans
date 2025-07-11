# .github/hooks/hook-fake_useragent.py
from PyInstaller.utils.hooks import collect_data_files

# Instruct PyInstaller to collect and bundle the data files
# from the 'fake_useragent' library. This is crucial for resolving
# the 'browsers.jsonl' not found error in the bundled executable.
datas = collect_data_files('fake_useragent')