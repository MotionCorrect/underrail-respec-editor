"""
Underrail Save Tool — attributes & skills editor (VERIFIED format, v1.3.1.2)
=============================================================================
Reverse-engineered and verified against two reference saves from Underrail v1.3.1.2.
See docs/ACKNOWLEDGMENTS.md and docs/REVERSE_ENGINEERING.md.

FILE FORMAT (global.dat):
    [24-byte header] + [gzip stream]
  The header embeds a data-model version. It MUST be preserved verbatim.
  Repack = original 24 bytes + gzip.compress(modified_payload).

ATTRIBUTE RECORDS (7x, in decompressed payload):
  Anchor: length-prefixed name string, e.g. b'\x08Strength'.
  Let np = offset of the name's FIRST LETTER (anchor offset + 1):
    int32 LE at np-20  = BASE value        (this is what you edit)
    int32 LE at np-16  = MODIFIED value    (base + gear/effects; keep delta)
  False positives exist elsewhere in the file; a real record satisfies:
    1 <= base <= 20  and  0 <= modified <= 40.
  Names: Strength, Dexterity, Agility, Constitution, Perception, Will,
  Intelligence.

SKILL RECORDS (24x, contiguous, fixed order):
  Anchor: the 5-byte marker b'\x04eSKC' followed IMMEDIATELY by
    b'\x02\x00\x00\x00\x02\x00\x00\x00' then byte 0x09.
  Values sit at marker_end + 13:
    int32 LE = ALLOCATED points (what you edit)
    int32 LE = EFFECTIVE value  (with attribute/synergy/gear bonuses)
  The 24 records appear in character-sheet order:
    Guns, Heavy Guns, Throwing, Crossbows, Melee, Dodge, Evasion, Stealth,
    Hacking, Lockpicking, Pickpocketing, Traps, Mechanics, Electronics,
    Chemistry, Biology, Tailoring, Thought Control, Psychokinesis,
    Metathermics, Temporal Manipulation, Persuasion, Intimidation, Mercantile
  Both saves examined contained EXACTLY 24 such markers (no false positives),
  but the tool still validates count == 24 and refuses to run otherwise.

EDITING POLICY:
  * Editing BASE/ALLOCATED also shifts MODIFIED/EFFECTIVE by the same delta,
    preserving gear/synergy bonuses. The game may recompute effective values
    on load anyway; writing consistent values is the conservative choice.
  * Per-skill legal cap at level L is 5*L+10. The tool warns (not blocks)
    beyond it. Attribute sanity range 1..20 (hard block outside).

USAGE (run from anywhere; paths can be a save folder or a global.dat):
  python -m underrail_respec_editor.save_tool show   <save_folder_or_global.dat>
  python -m underrail_respec_editor.save_tool clone  <save_folder> <new_name>
  python -m underrail_respec_editor.save_tool edit   <save_folder_or_global.dat> \
         [--attr Strength=8 ...] [--skill Crossbows=70 ...] [--level 12]
  'edit' always writes a timestamped .bak next to the target first.
Typical safe workflow:
  1) clone the source save folder to a new name
  2) edit the CLONE
  3) show the clone to verify
  4) load the clone in-game and check the character sheet
"""

import argparse
import gzip
import shutil
import struct
import sys
import time
from pathlib import Path

HEADER_LEN = 24
GZIP_MAGIC = b"\x1f\x8b"

ATTRS = ["Strength", "Dexterity", "Agility", "Constitution", "Perception",
         "Will", "Intelligence"]

SKILLS = ["Guns", "Heavy Guns", "Throwing", "Crossbows", "Melee", "Dodge",
          "Evasion", "Stealth", "Hacking", "Lockpicking", "Pickpocketing",
          "Traps", "Mechanics", "Electronics", "Chemistry", "Biology",
          "Tailoring", "Thought Control", "Psychokinesis", "Metathermics",
          "Temporal Manipulation", "Persuasion", "Intimidation", "Mercantile"]

SKILL_MARKER = b"\x04eSKC"
SKILL_MARKER_TAIL = b"\x02\x00\x00\x00\x02\x00\x00\x00"
SKILL_VALUE_OFFSET = 13  # from end of SKILL_MARKER

ATTR_MIN, ATTR_MAX = 1, 20


def lp(name: str) -> bytes:
    raw = name.encode("ascii")
    return bytes([len(raw)]) + raw


def resolve_dat(path: Path) -> Path:
    if path.is_dir():
        path = path / "global.dat"
    if not path.is_file():
        sys.exit(f"ERROR: {path} not found.")
    return path


class Save:
    def __init__(self, dat_path: Path):
        self.path = resolve_dat(dat_path)
        blob = self.path.read_bytes()
        if len(blob) <= HEADER_LEN or blob[HEADER_LEN:HEADER_LEN + 2] != GZIP_MAGIC:
            sys.exit("ERROR: not a packed Underrail file (bad header/gzip magic).")
        self.header = blob[:HEADER_LEN]
        self.data = bytearray(gzip.decompress(blob[HEADER_LEN:]))
        self.attr_pos = self._find_attrs()      # name -> np (first-letter offset)
        self.skill_pos = self._find_skills()    # name -> value offset

    # ---- attributes ----
    def _find_attrs(self):
        out = {}
        for a in ATTRS:
            pat = lp(a)
            cands = []
            s = 0
            while (i := self.data.find(pat, s)) != -1:
                np_ = i + 1
                if np_ >= 25:
                    base = struct.unpack_from("<i", self.data, np_ - 20)[0]
                    mod = struct.unpack_from("<i", self.data, np_ - 16)[0]
                    # Structural framing verified on live saves:
                    #   np-25 == 0x09 (record ref marker before the two int32s)
                    #   np-7, np-6 == 0x0a, 0x06 (framing right before the name)
                    structural = (self.data[np_ - 25] == 0x09
                                  and self.data[np_ - 7] == 0x0a
                                  and self.data[np_ - 6] == 0x06)
                    if structural and ATTR_MIN <= base <= ATTR_MAX and 0 <= mod <= 40:
                        cands.append(np_)
                s = i + 1
            if len(cands) != 1:
                sys.exit(f"ERROR: expected exactly 1 valid record for {a}, "
                         f"found {len(cands)}. Refusing to guess.")
            out[a] = cands[0]
        return out

    def get_attr(self, name):
        np_ = self.attr_pos[name]
        return (struct.unpack_from("<i", self.data, np_ - 20)[0],
                struct.unpack_from("<i", self.data, np_ - 16)[0])

    def set_attr(self, name, new_base):
        if not (ATTR_MIN <= new_base <= ATTR_MAX):
            sys.exit(f"ERROR: {name}={new_base} outside {ATTR_MIN}..{ATTR_MAX}.")
        np_ = self.attr_pos[name]
        base, mod = self.get_attr(name)
        delta = new_base - base
        struct.pack_into("<i", self.data, np_ - 20, new_base)
        struct.pack_into("<i", self.data, np_ - 16, mod + delta)

    # ---- skills ----
    def _find_skills(self):
        hits = []
        s = 0
        while (i := self.data.find(SKILL_MARKER, s)) != -1:
            p = i + len(SKILL_MARKER)
            if self.data[p:p + 8] == SKILL_MARKER_TAIL and self.data[p + 8] == 0x09:
                hits.append(p + SKILL_VALUE_OFFSET)
            s = i + 1
        if len(hits) != 24:
            sys.exit(f"ERROR: expected exactly 24 skill records, found {len(hits)}. "
                     "Format may have changed; refusing to edit.")
        return dict(zip(SKILLS, hits))

    def get_skill(self, name):
        v = self.skill_pos[name]
        return struct.unpack_from("<ii", self.data, v)

    def set_skill(self, name, new_alloc, level=None):
        if new_alloc < 0 or new_alloc > 400:
            sys.exit(f"ERROR: {name}={new_alloc} is absurd. 0..400 only.")
        if level is not None and new_alloc > 5 * level + 10:
            print(f"WARNING: {name}={new_alloc} exceeds legal cap "
                  f"{5 * level + 10} for level {level}. Writing anyway.")
        v = self.skill_pos[name]
        alloc, eff = self.get_skill(name)
        delta = new_alloc - alloc
        struct.pack_into("<ii", self.data, v, new_alloc, eff + delta)

    # ---- io ----
    def write(self):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"global.dat.{stamp}.bak")
        shutil.copy2(self.path, backup)
        self.path.write_bytes(self.header + gzip.compress(bytes(self.data)))
        return backup

    def show(self):
        print(f"File: {self.path}")
        print("-- Attributes (base / modified) --")
        for a in ATTRS:
            b, m = self.get_attr(a)
            extra = f"  ({m})" if m != b else ""
            print(f"  {a:14s} {b}{extra}")
        print("-- Skills (allocated / effective) --")
        for sk in SKILLS:
            al, ef = self.get_skill(sk)
            if al or ef:
                print(f"  {sk:22s} {al:3d}  ({ef})")
        total = sum(self.get_skill(sk)[0] for sk in SKILLS)
        print(f"  Total allocated skill points: {total}")


def cmd_clone(src: Path, new_name: str):
    if not src.is_dir():
        sys.exit(f"ERROR: {src} is not a save folder.")
    dst = src.parent / new_name
    if dst.exists():
        sys.exit(f"ERROR: {dst} already exists.")
    shutil.copytree(src, dst)
    print(f"Cloned save folder:\n  {src}\n  -> {dst}")
    print("The save list in-game uses the folder name; the clone will appear "
          f"as '{new_name}'.")


def kv_pairs(items, valid, kind):
    out = {}
    for item in items or []:
        if "=" not in item:
            sys.exit(f"ERROR: bad --{kind} '{item}', expected Name=Value.")
        k, v = item.split("=", 1)
        k = k.strip()
        match = [n for n in valid if n.lower() == k.lower()]
        if not match:
            sys.exit(f"ERROR: unknown {kind} '{k}'. Valid: {', '.join(valid)}")
        try:
            out[match[0]] = int(v)
        except ValueError:
            sys.exit(f"ERROR: value for {k} must be an integer.")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="print attributes and skills")
    p_show.add_argument("target")

    p_clone = sub.add_parser("clone", help="duplicate a save folder under a new name")
    p_clone.add_argument("src")
    p_clone.add_argument("new_name")

    p_edit = sub.add_parser("edit", help="edit attributes/skills (auto-backup)")
    p_edit.add_argument("target")
    p_edit.add_argument("--attr", action="append",
                        help="e.g. --attr Strength=8 (repeatable)")
    p_edit.add_argument("--skill", action="append",
                        help='e.g. --skill Crossbows=70 --skill "Thought Control=45"')
    p_edit.add_argument("--level", type=int, default=None,
                        help="character level, enables skill-cap warnings")

    args = ap.parse_args()

    if args.cmd == "clone":
        cmd_clone(Path(args.src), args.new_name)
        return

    if args.cmd == "show":
        Save(Path(args.target)).show()
        return

    if args.cmd == "edit":
        attrs = kv_pairs(args.attr, ATTRS, "attr")
        skills = kv_pairs(args.skill, SKILLS, "skill")
        if not attrs and not skills:
            sys.exit("Nothing to edit. Pass --attr and/or --skill.")
        sv = Save(Path(args.target))
        print("Before:")
        sv.show()
        for k, v in attrs.items():
            sv.set_attr(k, v)
        for k, v in skills.items():
            sv.set_skill(k, v, level=args.level)
        backup = sv.write()
        print(f"\nWritten. Backup: {backup}")
        print("After:")
        Save(Path(args.target)).show()


if __name__ == "__main__":
    main()
