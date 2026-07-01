import re
import os
import csv
import string
from mutagen import File as MutagenFile
print("Let's a-gooooo!")
manual_fixes = {
    "alma's phat mama": "alma's fat mama",
    "alma": "alma's fat mama",
    "alma's": "alma's fat mama",

    "goodnight": "and we bid you goodnight",
    "we bid you goodnight": "and we bid you goodnight",
    "wbygn": "and we bid you goodnight",

    "atoms": "atoms in pursuit",

    "biodtl": "beat it on down the line",

    "bott": "back on the train",

    "brokedown": "brokedown palace",

    "dialogue": "chatter",
    "post jam recap": "chatter",
    "post-jam recap": "chatter",
    "pjr": "chatter",
    "the last word": "chatter",
    "the post jam": "chatter",
    "the post": "chatter",

    "china cat": "china cat sunflower",
    "china": "china cat sunflower",

    "cold rain snow": "cold rain and snow",

    "cripple creek": "up on cripple creek",

    "cumberland": "cumberland blues",

    "dancin": "dancin in the street",
    "dancing": "dancin in the street",
    "dancing in the street": "dancin in the street",
    "dancing in the streets": "dancin in the street",
    "dancin in the streets": "dancin in the street",
    "dits": "dancin in the street",

    "dark star jam": "dark star",
    
    "dear mr fantasy": "dear mr. fantasy",

    "dixie down": "the night they drove old dixie down",

    "eyes": "eyes of the world",

    "fire": "fire on the mountain",
    "fotm": "fire on the mountain",

    "flas": "feel like a stranger",
    "feels like a stranger": "feel like a stranger",
    "stranger": "feel like a stranger",

    "fotd": "friend of the devil",

    "franklin": "franklin's tower",
    "franklins": "franklin's tower",
    "franklin's": "franklin's tower",
    
    "gdtrfb": "goin down the road feelin bad",
    "goin down the road feeling bad": "goin down the road feelin bad",
    "going down the road feeling bad": "goin down the road feelin bad",

    "schoolgirl": "good morning little schoolgirl",

    "how sweet it is (to be loved by you)": "how sweet it is",

    "rider": "i know you rider",

    "opening jam": "jam",
    "opening jam in a": "jam",
    "opening noodles": "jam",

    "johnny b goode": "johnny b. goode",

    "knockin lost john": "knockin' lost john",

    "good times": "let the good times roll",
    "good times roll": "let the good times roll",

    "cleveland": "look out cleveland",

    "muncle": "me and my uncle",
    "me & my uncle": "me and my uncle", 

    "half step": "mississippi half-step uptown toodeloo",
    "half-step": "mississippi half-step uptown toodeloo",
    "mississippi": "mississippi half-step uptown toodeloo",
    "mississippi half step uptown toodeloo": "mississippi half-step uptown toodeloo",
    "mississippi half-step": "mississippi half-step uptown toodeloo",
    "mississippi half step": "mississippi half-step uptown toodeloo",

    "new minglewood": "new minglewood blues",

    "new speedway": "new speedway boogie",

    "nfa": "not fade away",
    
    "osop": "other side of paradise",

    "playin": "playin in the band",
    "pitb": "playin in the band",
    "playing in the band": "playin in the band",

    "push": "push comes to shove",

    "samson": "samson and delilah",

    "scarlet": "scarlet begonias",

    "shakedown": "shakedown street",

    "sitting in limbo": "sitting here in limbo",

    "speak up": "speak up!",

    "tangled": "tangled up in blue",
    "tangled up": "tangled up in blue",

    "jed": "tennessee jed",

    "terrapin": "terrapin station",

    "music": "the music never stopped",
    "music never stopped": "the music never stopped",
    "tmns": "the music never stopped",

    "other one": "the other one",

    "weight": "the weight",

    "tleo": "they love each other",

    "lovelight": "turn on your lovelight",

    "cripple creek": "up on cripple creek",

    "viola": "viola lee blues",
    "viola lee": "viola lee blues",

    "way back": "way back home",

    "west la": "west l.a. fadeaway",
    "west la fadeaway": "west l.a. fadeaway",

    "wolfman": "wolfman's brother",
    "wolfman's": "wolfman's brother",

    "walcott": "w.s. walcott medicine show",
    "ws walcott": "w.s. walcott medicine show",
    "ws walcott medicine show": "w.s. walcott medicine show",
}

junk_terms = [
    " take 2",
    " take 3",
    " demo",
    "(voice lesson)",
    " (ending)", 
    " (opening)",
    " ending",
    " intro",
    " - master",
    "(soundcheck)",
    " (2)", " (3)", " (4)", " (5)", " (1)",
    " (6)", " (7)", " (8)", " (9)",
    "(instrumental)",
    "(dave guitar)",
    "(dave vox)",
    "(chris vox)",
    "(matt guitar)" 
]    

segue_fixes = {
    "scarlet fire": "scarlet_ fire",
    "china rider": "china_ rider",
    "china cat rider": "china_ rider",
    "help slip frank": "help_slip_frank",
    "walcott cumberland": "walcott_ cumberland"
}

archive_paths = [
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Gig Recordings",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2015-2020",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2021-",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Trips"
]

def get_duration(filepath):
    try:
        audio = MutagenFile(filepath)
        if audio is not None and audio.info is not None:
            seconds = int(audio.info.length)

            # if mutagen returned milliseconds instead of seconds
            if seconds > 10000:
                seconds = seconds // 1000

            if seconds > 3600:
                seconds = seconds // 60

            minutes = seconds // 60
            secs = seconds % 60
            if minutes >= 60:
                hours = minutes // 60
                minutes = minutes % 60
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"
    except Exception:
        pass
    return "N/A"

with open("band_archive.csv", "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)
    # column headers
    writer.writerow(["Track Number", "File Track", "Title", "Date", "Location", "Type", "Duration", "Raw Title", "File Path", "Take"])

    for archive_path in archive_paths:

        for root, dirs, files in os.walk(archive_path):
            logical_track_number = 1
            seen_songs = {}
            for file in sorted(files):
                if file.lower().endswith((".mp3", ".m4a", ".wav", ".wma", ".aac", ".bmp")):
                    
                    #track name and num
                    raw_name = os.path.splitext(file)[0]
                    # extract leading track number
                    match = re.match(r"^(\d+)[_ -]*(.*)", raw_name)

                    if match:
                        track_number = match.group(1)
                        raw_title = match.group(2).strip()
                    else:
                        track_number = ""
                        raw_title = raw_name
                    
                    # split segue songs
                    raw_title = raw_title.lower()

                    #fix segue songs (e.g. scarlet fire -> scarlet_ fire)
                    for old, new in segue_fixes.items():
                        raw_title = raw_title.replace(old, new)
                    
                    #remove junk words
                    for term in junk_terms:
                        raw_title = raw_title.replace(term, "")

                    #split segues
                    songs = [song.strip() for song in raw_title.split("_")]

                    for raw_song in songs:

                        # clean title
                        cleaned_title = raw_song.strip()
                        cleaned_title = cleaned_title.lower()
                        cleaned_title = cleaned_title.replace("  ", " ")

                        cleaned_title = re.sub(r"\s+jam$", "", cleaned_title)

                        if cleaned_title in manual_fixes:
                            cleaned_title = manual_fixes[cleaned_title]

                        title = string.capwords(cleaned_title)

                        # extract date/location
                        folder_name = os.path.basename(root)
                        date = folder_name[:10]

                        lower_root=root.lower()
                        if "gig" in lower_root:
                            recording_type = "live"
                            gig_place = folder_name.split(" _ ", 1)[1]
                        elif "trips" in lower_root:
                            recording_type = "trip"
                            gig_place = folder_name.split(" _ ", 1)[1]
                        else:
                            recording_type = "practice"
                            if date >= "2024-06-26": # date of first recording in new practice space
                                gig_place = "Danktuary Studios"
                            elif date >= "2020-03-10":
                                gig_place = "Studio Chill"
                            else:
                                gig_place = "The Music Building"
                        
                        filepath = os.path.join(root, file)
                        duration = get_duration(filepath)

                        if title not in seen_songs:
                            take = 1
                            display_title = title
                        else:
                            take = seen_songs[title] + 1
                            display_title = f"{title} ({take})"

                        writer.writerow([
                            logical_track_number,
                            track_number,
                            display_title,
                            date,
                            gig_place,
                            recording_type,
                            duration,
                            raw_name,
                            filepath,
                            take
                        ])
                        seen_songs[title] = take
                        logical_track_number += 1

print("CSV created successfully!")