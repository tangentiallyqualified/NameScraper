"""Realistic media-filename corpus for the parsing harness.

Entries are convention-accurate release names (scene TV, WEB-DL, anime
fansub, BDRip, movies) with the CORRECT expected parse. Only the keys
present on a record are asserted:

    name            (required) the filename/folder string under test
    episodes        expected extract_episode(name)[0]
    ep_title        expected extract_episode(name)[1]
    season_relative expected extract_episode(name)[2]
    season          expected extract_season_number(name)  (int | None)
    year            expected extract_year(name)           (str | None)
    is_tv           expected looks_like_tv_episode(Path(name))
    xfail           True when the parser is currently WRONG on >= 1 asserted
                    key; strict xfail, so fixing the parser forces the record
                    to be flipped to a real assertion
    note            human context / which key fails and why

Group names are invented but convention-accurate; the shape matters.
"""

CORPUS = [
    # -- Scene TV: HDTV / WEB-DL / BluRay ---------------------------------
    {
        "name": "Show.Name.S01E02.720p.HDTV.x264-LOL.mkv",
        "episodes": [2],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S01E01.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb.mkv",
        "episodes": [1],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S05E11.PROPER.720p.HDTV.x264-KILLERS.mkv",
        "episodes": [11],
        "season": 5,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S01E01.REPACK.1080p.WEB.H264-GROUP.mkv",
        "episodes": [1],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S04E22.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-GROUP.mkv",
        "episodes": [22],
        "season": 4,
        "is_tv": True,
    },
    {
        "name": "The.Office.US.S03E12.720p.HDTV.x264-LOL.mkv",
        "episodes": [12],
        "season": 3,
        "is_tv": True,
    },
    {"name": "Star.Trek.DS9.S06E13.mkv", "episodes": [13], "season": 6, "is_tv": True},
    {
        "name": "Breaking.Bad.S05E14.Ozymandias.1080p.BluRay.x264-DEMAND.mkv",
        "episodes": [14],
        "season": 5,
        "is_tv": True,
    },
    {
        "name": "Game.of.Thrones.S08E06.2160p.WEB-DL.DDP5.1.HDR.HEVC-GROUP.mkv",
        "episodes": [6],
        "season": 8,
        "is_tv": True,
    },
    {
        "name": "Better.Call.Saul.S06E13.1080p.NF.WEB-DL.DDP5.1.x264-NTb.mkv",
        "episodes": [13],
        "season": 6,
        "is_tv": True,
    },
    {
        "name": "The.Mandalorian.S02E08.1080p.DSNP.WEB-DL.DDP5.1.Atmos.H.264-GROUP.mkv",
        "episodes": [8],
        "season": 2,
        "is_tv": True,
    },
    {"name": "Ted.Lasso.S03E01.HDTV.x265-MiNX.mkv", "episodes": [1], "season": 3, "is_tv": True},
    {
        "name": "Severance.S01E09.2160p.ATVP.WEB-DL.x265.10bit.HDR-GROUP.mkv",
        "episodes": [9],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Succession.S04E10.1080p.HMAX.WEB-DL.DD5.1.H.264-playWEB.mkv",
        "episodes": [10],
        "season": 4,
        "is_tv": True,
    },
    {
        "name": "The.Bear.S02E10.1080p.DSNP.WEB-DL.DDP5.1.H.264-NTb.mkv",
        "episodes": [10],
        "season": 2,
        "is_tv": True,
    },
    {
        "name": "Fargo.S05E08.720p.HDTV.x264-SYNCOPY.mkv",
        "episodes": [8],
        "season": 5,
        "is_tv": True,
    },
    {
        "name": "Rick.and.Morty.S07E05.1080p.WEB.H264-GLHF.mkv",
        "episodes": [5],
        "season": 7,
        "is_tv": True,
    },
    {
        "name": "Loki.S02E06.HDR.2160p.WEB.H265-GROUP.mkv",
        "episodes": [6],
        "season": 2,
        "is_tv": True,
    },
    {"name": "The.Wire.S03E11.DVDRip.XviD-TVR.avi", "episodes": [11], "season": 3, "is_tv": True},
    {
        "name": "Mr.Robot.S04E13.1080p.AMZN.WEBRip.DDP5.1.x264-GROUP.mkv",
        "episodes": [13],
        "season": 4,
        "is_tv": True,
    },
    # Title contains a number -- S##E## must win over the title digits
    {
        "name": "The.100.S02E05.720p.HDTV.x264-KILLERS.mkv",
        "episodes": [5],
        "season": 2,
        "is_tv": True,
    },
    {"name": "2.Broke.Girls.S03E01.HDTV.x264-LOL.mkv", "episodes": [1], "season": 3, "is_tv": True},
    {"name": "Babylon.5.S01E01.720p.mkv", "episodes": [1], "season": 1, "is_tv": True},
    {"name": "9-1-1.S03E10.1080p.WEB.H264-GROUP.mkv", "episodes": [10], "season": 3, "is_tv": True},
    {"name": "24.S01E01.720p.HDTV.x264.mkv", "episodes": [1], "season": 1, "is_tv": True},
    {
        "name": "Warehouse.13.S02E05.720p.HDTV.x264-LOL.mkv",
        "episodes": [5],
        "season": 2,
        "is_tv": True,
    },
    {"name": "Area.51.S01E03.WEBRip.x264-GROUP.mkv", "episodes": [3], "season": 1, "is_tv": True},
    {
        "name": "Person.of.Interest.S03E10.720p.HDTV.x264-DIMENSION.mkv",
        "episodes": [10],
        "season": 3,
        "is_tv": True,
    },
    # Year present in a TV name -- extract_year should still find it
    {
        "name": "Show Name 2010 S01E01 1080p.mkv",
        "episodes": [1],
        "season": 1,
        "year": "2010",
        "is_tv": True,
    },
    {
        "name": "Doctor.Who.2005.S01E01.720p.BluRay.x264-GROUP.mkv",
        "episodes": [1],
        "season": 1,
        "year": "2005",
        "is_tv": True,
    },
    {
        "name": "Watchmen.S01.2160p.MAX.WEB-DL",
        "year": None,
        "is_tv": True,
        "xfail": True,
        "note": "season pack: bare S## in a FILE name is not yet a TV signal (only checked on parents)",
    },
    # -- Multi-episode variants -------------------------------------------
    {
        "name": "Show.Name.S01E01E02.720p.HDTV.x264-LOL.mkv",
        "episodes": [1, 2],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S01E01-E02.720p.HDTV.x264-LOL.mkv",
        "episodes": [1, 2],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S01E01-E03.1080p.WEB-DL.mkv",
        "episodes": [1, 2, 3],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S01E01E02E03.720p.HDTV.x264-LOL.mkv",
        "episodes": [1, 2, 3],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S02E05E06.1080p.WEB.H264-GROUP.mkv",
        "episodes": [5, 6],
        "season": 2,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S01E12-E13.HDTV.x264-GROUP.mkv",
        "episodes": [12, 13],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "Show.Name.S03E07-E08-E09.720p.mkv",
        "episodes": [7, 8, 9],
        "season": 3,
        "is_tv": True,
    },
    # episode markers WITHOUT a season prefix (P-H1 / P-M2)
    {
        "name": "Show E01-E02.mkv",
        "episodes": [1, 2],
        "note": "P-H1: episode-marker chain without a season prefix",
    },
    {
        "name": "Show E01E02.mkv",
        "episodes": [1, 2],
        "note": "P-H1: episode-marker chain without a season prefix",
    },
    {
        "name": "Show EP01-EP02.mkv",
        "episodes": [1, 2],
        "note": "P-H1: episode-marker chain without a season prefix",
    },
    {
        "name": "Show 01-02.mkv",
        "episodes": [1, 2],
        "note": "P-M2: adjacent NN-NN range at a token boundary",
    },
    {
        "name": "Show E01 - E02.mkv",
        "episodes": [1, 2],
        "note": "P-H1: spaced-dash episode-marker chain",
    },
    # -- NxNN / 1x02 -------------------------------------------------------
    {"name": "Show.Name.1x02.720p.HDTV.mkv", "episodes": [2], "season": 1, "is_tv": True},
    {"name": "Show Name 3x08.mkv", "episodes": [8], "season": 3, "is_tv": True},
    {"name": "Show.Name.10x24.WEBRip.mkv", "episodes": [24], "season": 10, "is_tv": True},
    {"name": "Show.Name.2x05-2x06.HDTV.mkv", "episodes": [5, 6], "season": 2, "is_tv": True},
    {"name": "Show.Name.1x100.WEB.mkv", "episodes": [100], "season": 1, "is_tv": True},
    # -- Anime fansub: [Group] Title - NN ---------------------------------
    {"name": "[SubsPlease] Frieren - 12 (1080p) [ABCD1234].mkv", "episodes": [12], "is_tv": True},
    {"name": "[HorribleSubs] Show - 01 [720p].mkv", "episodes": [1], "is_tv": True},
    {
        "name": "[Erai-raws] Show - 07 [1080p][Multiple Subtitle][ABC12345].mkv",
        "episodes": [7],
        "is_tv": True,
    },
    {"name": "[SubsPlease] Show - 100 (1080p).mkv", "episodes": [100], "is_tv": True},
    {
        "name": "[EMBER] Show Name - 03 [1080p][HEVC WEBRip AAC][Dual Audio].mkv",
        "episodes": [3],
        "is_tv": True,
    },
    {"name": "[ASW] Show Name - 08 [1080p HEVC][A1B2C3D4].mkv", "episodes": [8], "is_tv": True},
    {
        "name": "[Anime Time] Show Name - 24 [1080p][HEVC 10bit x265][AAC].mkv",
        "episodes": [24],
        "is_tv": True,
    },
    {
        "name": "[Judas] Show Name - S01E05 [1080p][HEVC x265 10bit][Multi-Subs].mkv",
        "episodes": [5],
        "season": 1,
        "is_tv": True,
    },
    {
        "name": "[Kawaiika-Raws] Bartender 02 [BDRip 1920x1080 HEVC FLAC].mkv",
        "episodes": [2],
        "is_tv": True,
        "xfail": True,
        "note": "fansub form without the spaced dash ([Group] Title NN) is not a TV signal yet",
    },
    {
        "name": "[Judas] Kaguya-sama - 11 [1080p][HEVC][x265][10bit].mkv",
        "episodes": [11],
        "is_tv": True,
    },
    {
        "name": "[Group] Kaguya-sama wa Kokurasetai S2 - 05 [1080p].mkv",
        "episodes": [5],
        "is_tv": True,
        "note": "S2 in the title is not an S##E## marker; dash episode wins",
    },
    {
        "name": "Gundam 0080 - War in the Pocket - 03.mkv",
        "episodes": [3],
        "note": "bare-dash absolute; is_tv unasserted (bare-dash form needs a [group] bracket today)",
    },
    {"name": "Mobile Suit Gundam - 0083 Stardust Memory - 05 - Title.mkv", "episodes": [5]},
    {
        "name": "[Group] Show Name - 05v2 [BDRip 1080p].mkv",
        "episodes": [5],
        "is_tv": True,
        "note": "C-7: v2 version tag must not break fansub dash TV detection",
    },
    {
        "name": "[Group] Show Name - 12 [BD 1080p FLAC].sample.mkv",
        "episodes": [12],
        "is_tv": True,
        "note": "sample flag is a separate is_sample_file() concern",
    },
    # -- Anime fully-bracketed: [Group][Title][NN] ------------------------
    {
        "name": "[DBD-Raws][Wolf's Rain][01][1080P][BDRip][HEVC-10bit][FLACx2].mkv",
        "episodes": [1],
        "is_tv": True,
    },
    {
        "name": "[DBD-Raws][Wolf's Rain][09][1080P][BDRip][HEVC-10bit][FLACx2].mkv",
        "episodes": [9],
        "is_tv": True,
    },
    {
        "name": "[DBD-Raws][Wolf's Rain][30][1080P][BDRip][HEVC-10bit][FLACx2].mkv",
        "episodes": [30],
        "is_tv": True,
    },
    {
        "name": "[Beatrice-Raws][Steins Gate][12][BDRip 1920x1080 HEVC FLAC].mkv",
        "episodes": [12],
        "is_tv": True,
    },
    {"name": "[Moozzi2][Show Name][03][BD 1080p x265 FLAC].mkv", "episodes": [3], "is_tv": True},
    {
        "name": "[VCB-Studio][Show Name][24][Ma10p_1080p][x265_flac].mkv",
        "episodes": [24],
        "is_tv": True,
    },
    # non-episode brackets must NOT be read as episodes
    {"name": "[Group][Show][1080P][BDRip][HEVC-10bit].mkv", "episodes": [], "is_tv": False},
    {"name": "[Group][Show][480p][x265].mkv", "episodes": [], "is_tv": False},
    {"name": "[Group][Show][v2][HEVC-10bit].mkv", "episodes": [], "is_tv": False},
    {"name": "[Group][Show][B36160B7].mkv", "episodes": [], "is_tv": False},
    {"name": "[Group][Show][2006][BDRip].mkv", "episodes": [], "is_tv": False},
    # -- Anime absolute numbering, incl. long runners ---------------------
    {"name": "Bleach - 366.mkv", "episodes": [366]},
    {"name": "[SubsPlease] Show - 999 (1080p).mkv", "episodes": [999], "is_tv": True},
    {
        "name": "One.Piece.S01E1071.1080p.WEB.mkv",
        "episodes": [1071],
        "season": 1,
        "is_tv": True,
        "note": "S##E#### works today (E\\d+ is unbounded); the dash paths are the capped ones",
    },
    {
        "name": "[Erai-raws] One Piece - 1071 [1080p][HEVC].mkv",
        "episodes": [1071],
        "is_tv": True,
        "note": "C-2: 4-digit absolute episode (long-running anime)",
    },
    {
        "name": "[Judas] Detective Conan - 1000 [1080p][HEVC].mkv",
        "episodes": [1000],
        "is_tv": True,
        "note": "C-2: 4-digit absolute episode",
    },
    {
        "name": "Naruto Shippuden - 500 [1080p].mkv",
        "episodes": [500],
        "is_tv": True,
        "xfail": True,
        "note": "episodes parse fine; is_tv False because bare-dash absolute requires a [group] bracket",
    },
    {
        "name": "One Piece - 720.mkv",
        "episodes": [720],
        "note": "P-H2: a bare dash number equal to a resolution value is still an episode",
    },
    {
        "name": "[Group] One Piece - 1080 [x264].mkv",
        "episodes": [1080],
        "note": "P-H2 + C-2: resolution-value episode in dash position",
    },
    # -- BDRips / season packs --------------------------------------------
    {
        "name": "[Group] Show Name S01 [BDRip 1080p HEVC].mkv",
        "episodes": [],
        "note": "C-8: season pack (no E##) must not yield a phantom episode",
    },
    {
        "name": "Show.Name.S01.COMPLETE.1080p.BluRay.x264-GROUP",
        "episodes": [],
        "note": "C-8: season pack must not yield a phantom episode",
    },
    {
        "name": "[Group] Show Name (01-12) [Batch][1080p].mkv",
        "episodes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "xfail": True,
        "note": "batch range in parens not recognized; deferred (needs range-vs-title policy)",
    },
    {
        "name": "Show.Name.Season.1.1080p.BluRay.x264-GROUP",
        "is_tv": True,
        "note": "spelled-out Season N in the filename is a TV signal",
    },
    # -- Specials / extras --------------------------------------------------
    {
        "name": "Show.Name.S00E01.Special.720p.HDTV.x264.mkv",
        "episodes": [1],
        "season": 0,
        "is_tv": True,
    },
    {"name": "Show.Name.S00E05.mkv", "episodes": [5], "season": 0, "is_tv": True},
    {"name": "Show.Name.S01E00.Recap.mkv", "episodes": [0], "season": 1, "is_tv": True},
    {
        "name": "[Group] Show Name - NCED01 [1080p].mkv",
        "is_tv": True,
        "note": "creditless ending is a companion video (counts as TV-adjacent)",
    },
    {"name": "[Group] Show Name - NCOP2 [1080p].mkv", "is_tv": True},
    {"name": "[Group] Show - OAD [1080p].mkv", "episodes": []},
    # -- Date-based shows ----------------------------------------------------
    {
        "name": "The.Daily.Show.2024.01.15.720p.WEB.x264-GROUP.mkv",
        "episodes": [],
        "year": "2024",
        "is_tv": True,
        "note": "P-M1/C-4: air date must not be read as an episode; date form is a TV signal",
    },
    {
        "name": "The.Tonight.Show.2023.11.02.Guest.720p.HDTV.x264.mkv",
        "episodes": [],
        "year": "2023",
        "is_tv": True,
        "note": "P-M1/C-4: air date must not be read as an episode",
    },
    {
        "name": "60.Minutes.2024.01.15.mkv",
        "episodes": [],
        "year": "2024",
        "note": "P-M1/C-4: date digits must not become episodes",
    },
    {
        "name": "SNL.2023.10.14.Pete.Davidson.1080p.WEB.h264-GROUP.mkv",
        "episodes": [],
        "year": "2023",
        "is_tv": True,
        "note": "P-M1/C-4: date-based daily show",
    },
    # -- Bare-number / prefix episode forms --------------------------------
    {"name": "01. Pilot.mkv", "episodes": [1], "is_tv": True},
    {"name": "Ep.05 - The Reveal.mkv", "episodes": [5], "is_tv": True},
    {"name": "Episode 07 - Title.mkv", "episodes": [7], "is_tv": True},
    {
        "name": "Show Name - 100 - Title.mkv",
        "episodes": [100],
        "is_tv": True,
        "xfail": True,
        "note": "episodes parse fine; is_tv False (bare-dash absolute needs a [group] bracket today)",
    },
    {
        "name": "Show.Name.101.720p.HDTV.x264.mkv",
        "episodes": [101],
        "note": "ambiguous 3-digit: parser reads absolute 101, not S1E01 (documented policy)",
    },
    {
        "name": "Season 1 Episode 2 - Title.mkv",
        "episodes": [2],
        "season": 1,
        "is_tv": True,
        "note": "P-M3: spelled-out Season N recognized by extract_season_number",
    },
    # -- Numeric-in-title guards (must NOT episode-parse) --------------------
    {
        "name": "Se7en.1995.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "1995",
        "is_tv": False,
    },
    {
        "name": "[CBM]_Blue_Submarine_No.6_(Toonami_Version)_[v2]_[H.265_10bit]_[B36160B7].mkv",
        "episodes": [],
        "is_tv": False,
    },
    {"name": "Futurama University - 3D Modeling.mkv", "episodes": []},
    {"name": "Storyboard Animatic Into the Wild Green Yonder, Part 1.mkv", "episodes": []},
    {"name": "Show.Name.Part.1.720p.mkv", "episodes": []},
    # -- Movies: scene releases ---------------------------------------------
    {
        "name": "Inception.2010.1080p.BluRay.x264-SPARKS.mkv",
        "episodes": [],
        "year": "2010",
        "is_tv": False,
    },
    {
        "name": "The.Matrix.1999.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "1999",
        "is_tv": False,
    },
    {
        "name": "Parasite.2019.2160p.UHD.BluRay.x265-GROUP.mkv",
        "episodes": [],
        "year": "2019",
        "is_tv": False,
    },
    {
        "name": "Dune.2021.IMAX.2160p.WEB-DL.DDP5.1.Atmos.HDR.HEVC-GROUP.mkv",
        "episodes": [],
        "year": "2021",
        "is_tv": False,
        "note": "audio-channel token DDP5.1 must not yield a phantom episode (corpus-triage find)",
    },
    {
        "name": "Oppenheimer.2023.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2023",
        "is_tv": False,
    },
    {
        "name": "The.Lord.of.the.Rings.The.Two.Towers.2002.EXTENDED.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2002",
        "is_tv": False,
    },
    {
        "name": "1917.2019.1080p.BluRay.x264-SPARKS.mkv",
        "episodes": [],
        "year": "2019",
        "is_tv": False,
        "note": "1917 falls in the year range, so it is not read as an episode",
    },
    {
        "name": "Blade.Runner.2049.2017.2160p.UHD.BluRay.x265-GROUP.mkv",
        "episodes": [],
        "year": "2017",
        "is_tv": False,
    },
    {
        "name": "Ocean's.Eleven.2001.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2001",
        "is_tv": False,
    },
    {
        "name": "2001.A.Space.Odyssey.1968.2160p.UHD.BluRay-GROUP.mkv",
        "episodes": [],
        "year": "1968",
        "is_tv": False,
    },
    # -- Movies: Plex / parenthetical style ----------------------------------
    {"name": "Movie Name (2010) [1080p].mkv", "episodes": [], "year": "2010", "is_tv": False},
    {"name": "The Matrix (1999).mkv", "episodes": [], "year": "1999", "is_tv": False},
    {
        "name": "Interstellar (2014) [2160p] [BluRay].mkv",
        "episodes": [],
        "year": "2014",
        "is_tv": False,
    },
    {"name": "Spirited Away (2001).mkv", "episodes": [], "year": "2001", "is_tv": False},
    {
        "name": "Whiplash (2014) [1080p] [YTS.AM].mp4",
        "episodes": [],
        "year": "2014",
        "is_tv": False,
    },
    # -- Movies: REPACK/PROPER/EXTENDED/DC/REMASTERED tags --------------------
    {
        "name": "Movie.Name.2015.PROPER.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2015",
        "is_tv": False,
    },
    {
        "name": "Movie.Name.2015.Directors.Cut.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2015",
        "is_tv": False,
    },
    {
        "name": "Movie.Name.2010.EXTENDED.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2010",
        "is_tv": False,
    },
    {
        "name": "Blade.Runner.1982.REMASTERED.Final.Cut.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "1982",
        "is_tv": False,
    },
    {
        "name": "Movie.Name.2018.REPACK.2160p.WEB-DL.x265-GROUP.mkv",
        "episodes": [],
        "year": "2018",
        "is_tv": False,
    },
    # -- Movies with a bare number in the title (phantom-episode bugs, C-1) ----
    {
        "name": "Apollo.13.1995.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "1995",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "District.9.2009.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2009",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "Super.8.2011.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2011",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "Fahrenheit.451.2018.1080p.WEB-DL.mkv",
        "episodes": [],
        "year": "2018",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "300.2006.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2006",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "21.Jump.Street.2012.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2012",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "Catch.22.1970.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "1970",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "Toy.Story.3.2010.1080p.BluRay.x264-GROUP.mkv",
        "episodes": [],
        "year": "2010",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "Slap.Shot.2.2002.DVDRip.XviD-GROUP.avi",
        "episodes": [],
        "year": "2002",
        "is_tv": False,
        "note": "C-1: bare title number followed by a year is not an episode",
    },
    {
        "name": "Area.88.OVA.01.mkv",
        "episodes": [1],
        "xfail": True,
        "note": "title number 88 wins over the real episode 01; deferred (needs OVA-number policy)",
    },
    {
        "name": "Evangelion.1.11.You.Are.Not.Alone.2007.1080p.BluRay.mkv",
        "episodes": [],
        "year": "2007",
        "is_tv": False,
        "xfail": True,
        "note": "version number 1.11 yields phantom episode [1]; deferred",
    },
    # movies where the guard already works (regression locks)
    {
        "name": "Gundam.0083.Stardust.Memory.2007.1080p.BluRay.x264-GROUP.mkv",
        "year": "2007",
        "is_tv": False,
    },
    # -- Year-season / format oddities ----------------------------------------
    {
        "name": "Show.Name.S2020E01.1080p.WEB.mkv",
        "episodes": [1],
        "season": 2020,
        "is_tv": True,
        "xfail": True,
        "note": "4-digit year-season: episode/season parse, but looks_like_tv_episode caps at S\\d{1,2}; deferred",
    },
    {
        "name": "Show.Name.1x01x02.720p.mkv",
        "episodes": [1, 2],
        "season": 1,
        "is_tv": True,
        "xfail": True,
        "note": "1x01x02 cross-format multi-episode unsupported; deferred",
    },
    # -- Subtitle / companion / sample files -----------------------------------
    {"name": "Show.Name.S01E05.1080p.WEB-DL.mkv.srt", "episodes": [5], "season": 1, "is_tv": True},
    {"name": "Show.Name.S01E05.en.srt", "episodes": [5], "season": 1, "is_tv": True},
    {"name": "Show.Name.S02E03.eng.forced.ass", "episodes": [3], "season": 2, "is_tv": True},
    {"name": "Show.Name.S01E02.multi.mkv.sample.mkv", "episodes": [2], "season": 1, "is_tv": True},
    # -- extract_episode branch characterization (seam refactor pins) -----
    # S##E## chains and ranges
    {"name": "Show.S01E01-E04.720p.mkv", "episodes": [1, 2, 3, 4], "season_relative": True},
    {"name": "Show.S01E03E05.mkv", "episodes": [3, 5], "season_relative": True},
    {"name": "Show.S01E01E02-04.mkv", "episodes": [1, 2, 4], "season_relative": True},
    {
        "name": "Show S01E05 - Title Words.mkv",
        "episodes": [5],
        "ep_title": "Title Words",
        "season_relative": True,
    },
    # NxNN chains and ranges
    {"name": "Show 1x05.mkv", "episodes": [5], "season_relative": True},
    {"name": "Show 1x05 - 1x07.mkv", "episodes": [5, 6, 7], "season_relative": True},
    {"name": "Show 1x05-07.mkv", "episodes": [5, 6, 7], "season_relative": True},
    # Air-date naming carries no episode evidence
    {"name": "The.Daily.Show.2024.03.11.Guest.720p.mkv", "episodes": [], "season_relative": False},
    {"name": "Show 2023-11-05 Special.mkv", "episodes": [], "season_relative": False},
    # Season-less E-chains
    {"name": "Show E01E02.mkv", "episodes": [1, 2], "season_relative": False},
    {"name": "Show EP01-EP03.mkv", "episodes": [1, 2, 3], "season_relative": False},
    # Adjacent NN-NN range at a token boundary
    {"name": "Show 01-02.mkv", "episodes": [1, 2], "season_relative": False},
    # Dash-delimited absolute numbers (anime convention)
    {
        "name": "Anime - 05 - Title Words.mkv",
        "episodes": [5],
        "ep_title": "Title Words",
        "season_relative": False,
    },
    {"name": "Anime - 1079.mkv", "episodes": [1079], "season_relative": False},
    {"name": "Anime - 05v2.mkv", "episodes": [5], "season_relative": False},
    # Leading "NN." numbering with year guards
    {
        "name": "01. Pilot (2005).mkv",
        "episodes": [1],
        "ep_title": "Pilot",
        "season_relative": False,
    },
    {"name": "300.2006.1080p.mkv", "episodes": [], "season_relative": False},
    # Explicit Ep/Episode prefix ignores resolution collisions
    {"name": "Show Episode 720.mkv", "episodes": [720], "season_relative": False},
    # Bare-number guards: embedded digits, quantity words, year-after-number
    {"name": "Se7en.1080p.mkv", "episodes": [], "season_relative": False},
    {"name": "Blue Submarine No.6.mkv", "episodes": [], "season_relative": False},
    {"name": "Apollo 13 1995 1080p.mkv", "episodes": [], "season_relative": False},
    # Bracketed absolute fansub numbering
    {"name": "[Group] Wolfs Rain [01][1080p].mkv", "episodes": [1], "season_relative": False},
    {"name": "[Group] Gundam [0083][BDRip].mkv", "episodes": [], "season_relative": False},
]
