words = [
    "acorn", "amber", "anvil", "apple", "arrow", "aspen", "atlas", "badge",
    "baker", "basil", "beach", "bell", "birch", "blade", "blaze", "bloom",
    "board", "bonus", "brave", "brick", "bridge", "brook", "brush", "cabin",
    "camel", "candy", "cape", "cargo", "cedar", "chalk", "chase", "chess",
    "chief", "cider", "cliff", "clock", "cloud", "coach", "coast", "cobra",
    "comet", "coral", "crane", "creek", "crest", "cross", "crown", "crush",
    "curve", "dance", "dawn", "delta", "denim", "derby", "desk", "digit",
    "diver", "dodge", "dove", "draft", "dream", "drift", "drum", "dusk",
    "eagle", "ember", "epoch", "equal", "event", "extra", "fable", "falcon",
    "feast", "fence", "field", "flame", "flash", "fleet", "flint", "float",
    "flood", "flora", "focus", "forge", "forum", "frost", "fruit", "gamma",
    "gavel", "gaze", "ghost", "glade", "glass", "gleam", "globe", "grace",
    "grain", "grape", "grasp", "grove", "guard", "guide", "haven", "hawk",
    "hazel", "heart", "hedge", "heron", "honey", "house", "ivory", "jade",
    "jewel", "joint", "judge", "kayak", "kite", "knack", "knoll", "lace",
    "lance", "latch", "lemon", "lever", "light", "lilac", "linen", "lodge",
    "lotus", "lunar", "maple", "march", "marsh", "mason", "match", "medal",
    "merge", "mesa", "metal", "minor", "mirth", "mixer", "moat", "model",
    "molar", "moss", "mural", "nerve", "night", "noble", "north", "novel",
    "oasis", "ocean", "olive", "onset", "opera", "orbit", "otter", "oxide",
    "paint", "panel", "patch", "pearl", "pedal", "penny", "phase", "pilot",
    "pixel", "plank", "plaza", "plume", "point", "polar", "pond", "poppy",
    "pouch", "prism", "prose", "pulse", "quake", "quest", "quiet", "quilt",
    "radar", "rapid", "raven", "realm", "ridge", "rivet", "robin", "rocky",
    "rover", "royal", "sable", "sage", "scale", "scout", "shade", "shark",
    "shell", "shine", "sigma", "silk", "slate", "slope", "smith", "solar",
    "spark", "spice", "spine", "spoke", "stamp", "steel", "stone", "storm",
    "stove", "surge", "sweet", "swift", "table", "talon", "thorn", "tiger",
    "timber", "toast", "torch", "tower", "trail", "trend", "trout", "tulip",
    "ultra", "umbra", "unity", "upper", "urban", "valve", "vault", "vigor",
    "viola", "vivid", "vocal", "watch", "water", "wheat", "wheel", "wing",
    "woven", "yacht", "yield", "zephyr", "zinc", "zone", "alder", "bliss",
]
assert len(words) == 256, f"Got {len(words)}"
assert len(set(words)) == 256, "Duplicates found"
for w in words:
    assert w.isalpha() and w.islower() and 3 <= len(w) <= 10, f"Bad word: {w}"
with open("/Users/cahnd/Documents/GitHub/agent-wormhole/src/agent_wormhole/words.txt", "w") as f:
    f.write("\n".join(words) + "\n")
print(f"Wrote {len(words)} words")
