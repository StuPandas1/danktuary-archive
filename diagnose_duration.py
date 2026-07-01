"""
Diagnostic: prints exactly what mutagen reports for one file, with no
correction logic applied, so we can see the real raw numbers.

Edit FILEPATH below, then run: python diagnose_duration.py
"""
from mutagen import File as MutagenFile

FILEPATH = r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2015-2020\2015\2015-03-04 _ Jam Session\09 Big River _ Magic Bus _ Lost _ Sunshine Of Your Love.m4a"

print(f"Checking: {FILEPATH}")
print("-" * 60)

audio = MutagenFile(FILEPATH)

if audio is None:
    print("mutagen.File() returned None — could not read this file at all.")
elif audio.info is None:
    print("File read, but audio.info is None.")
else:
    raw_length = audio.info.length
    print(f"audio.info.length (raw):     {raw_length}")
    print(f"type:                        {type(raw_length)}")
    print(f"int(raw_length):             {int(raw_length)}")
    print(f"as minutes:                  {raw_length / 60:.2f}")
    print(f"as hours:                    {raw_length / 3600:.2f}")
    print()
    print(f"mutagen object type:         {type(audio).__name__}")
    print(f"audio.info type:             {type(audio.info).__name__}")
    print()
    print("All numeric-looking attributes on audio.info:")
    for attr in dir(audio.info):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(audio.info, attr)
            if isinstance(val, (int, float)):
                print(f"  {attr}: {val}")
        except Exception:
            pass
