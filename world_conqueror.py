#!/usr/bin/env python3
"""
World Conqueror
A turn-based country conquest / diplomacy game — single file, no dependencies.

Features:
  - Geography: attacks must be land-adjacent or require a navy for overseas invasion
  - Territory-level combat: conquer one province at a time, not whole nations in one hit
  - Unit types (infantry / navy / air / nukes) with a rock-paper-scissors counter system
  - AI opponents that build, ally, sign pacts, hold grudges, and gang up on the leader
  - Non-aggression pacts, alliances, and mergers
  - Espionage: spy on rivals to see their true stats, or sabotage them
  - Fog of war: unspied rivals show only fuzzy estimates of their strength
  - Save / load games to a local JSON file
  - Difficulty settings
  - Colorized terminal output
  - Multiple victory conditions: conquest, economic, alliance dominance, or turn-limit score
"""

import random
import sys
import time
import json
import os
from collections import defaultdict

# ----------------------------------------------------------------------------
# Color helpers (ANSI escape codes — supported by most modern terminals)
# ----------------------------------------------------------------------------

class Col:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    ORANGE = "\033[38;5;208m"
    GREY = "\033[38;5;245m"


def c(text, *codes):
    return "".join(codes) + str(text) + Col.RESET


# ----------------------------------------------------------------------------
# ASCII art — little Oregon-Trail-style "event cards" for big moments
# ----------------------------------------------------------------------------

MUSHROOM_CLOUD = [
    (r"          ___             ", Col.GREY),
    (r"       .-'   `-.          ", Col.GREY),
    (r"     .'  .-'''-. `.       ", Col.YELLOW),
    (r"    /  .'  ___  `. \      ", Col.ORANGE),
    (r"   |  /  .'   `.  \ |     ", Col.RED),
    (r"   | |  |  ☢  |  | |     ", Col.RED),
    (r"   |  \  `.___.'  / |     ", Col.ORANGE),
    (r"    \  `.       .'  /     ", Col.YELLOW),
    (r"     `.  `-----'  .'      ", Col.GREY),
    (r"       `-.     .-'        ", Col.GREY),
    (r"          |   |           ", Col.DIM),
    (r"          |   |           ", Col.DIM),
    (r"         .|   |.          ", Col.DIM),
    (r"        / |   | \         ", Col.DIM),
    (r"       '--'   '--'        ", Col.DIM),
]

TROPHY_ART = [
    (r"      ___________       ", Col.YELLOW),
    (r"      \\  ..  ..  //     ", Col.YELLOW),
    (r"       \\        //      ", Col.YELLOW),
    (r"        )      (        ", Col.YELLOW),
    (r"       /  WIN!  \       ", Col.BOLD + Col.YELLOW),
    (r"      /__________\      ", Col.YELLOW),
    (r"           ||            ", Col.GREY),
    (r"         ~~~~~~~        ", Col.GREY),
]

SKULL_ART = [
    (r"       _____        ", Col.WHITE),
    (r"      /     \       ", Col.WHITE),
    (r"     | () () |      ", Col.RED),
    (r"      \  ^  /       ", Col.WHITE),
    (r"       |||||        ", Col.WHITE),
    (r"       |||||        ", Col.GREY),
]


def print_art(art):
    for line, color in art:
        print(c(line, color))


def nuke_flash():
    """A quick colored 'flash' effect before the mushroom cloud renders."""
    frames = [Col.WHITE, Col.YELLOW, Col.ORANGE, Col.RED]
    for color in frames:
        sys.stdout.write("\r" + c("*" * 40, color))
        sys.stdout.flush()
        time.sleep(0.06)
    print()


# ----------------------------------------------------------------------------
# "Corner popup" notifications — small right-aligned boxed call-outs so
# important stuff (attacks on you, proposals, events) stands out from the
# scrolling log instead of blending into it.
# ----------------------------------------------------------------------------

TERMINAL_WIDTH = 78


def print_popup(lines, title=None, color=Col.CYAN):
    """Render a small boxed notification, right-aligned like a corner toast."""
    content = ([title] if title else []) + list(lines)
    box_inner = max((len(l) for l in content), default=10) + 2
    indent = max(0, TERMINAL_WIDTH - box_inner - 2)
    pad = " " * indent
    print(pad + c("╭" + "─" * box_inner + "╮", color))
    if title:
        print(pad + c("│ " + c(title, Col.BOLD) + " " * (box_inner - 2 - len(title)) + " │", color))
        print(pad + c("├" + "─" * box_inner + "┤", color))
    for l in lines:
        print(pad + c("│ " + l.ljust(box_inner - 2) + " │", color))
    print(pad + c("╰" + "─" * box_inner + "╯", color))


class NotificationCenter:
    """Queues up little events during a turn so they can be flushed as a
    batch of popups at a natural break point, instead of interrupting
    whatever's currently printing."""

    def __init__(self):
        self.queue = []  # list of (title, [lines], color)

    def push(self, title, lines, color=Col.CYAN):
        self.queue.append((title, lines if isinstance(lines, list) else [lines], color))

    def flush(self):
        if not self.queue:
            return
        for title, lines, color in self.queue:
            print_popup(lines, title=title, color=color)
        self.queue.clear()


# ----------------------------------------------------------------------------
# Menu helpers — numbered submenus rendered as boxes
# ----------------------------------------------------------------------------

def print_menu_box(title, options):
    """options: list of (key, label) tuples. Renders a boxed numbered menu."""
    lines = [f"[{key}] {label}" for key, label in options]
    width = max(len(title), max((len(l) for l in lines), default=10)) + 2
    print(c("╔" + "═" * width + "╗", Col.BOLD, Col.CYAN))
    print(c("║ " + title.ljust(width - 1) + "║", Col.BOLD, Col.CYAN))
    print(c("╠" + "═" * width + "╣", Col.BOLD, Col.CYAN))
    for l in lines:
        print(c("║ " + l.ljust(width - 1) + "║", Col.CYAN))
    print(c("╚" + "═" * width + "╝", Col.BOLD, Col.CYAN))


def menu_choice(title, options, allow_back=True):
    """options: list of (key, label). Returns the chosen key (str), or None
    if the user backs out / enters something invalid."""
    opts = list(options)
    if allow_back:
        opts = opts + [("0", "Back")]
    print_menu_box(title, opts)
    choice = input("> ").strip().lower()
    valid_keys = {k.lower() for k, _ in opts}
    if choice in valid_keys:
        if allow_back and choice == "0":
            return None
        return choice
    print(c("Invalid choice.", Col.YELLOW))
    return None


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

COUNTRIES_DATA = {
    "United States": {"short_name": "US", "flag": "🇺🇸", "population": 330_000_000, "resources": 100, "military": 70},
    "Canada":        {"short_name": "CA", "flag": "🇨🇦", "population": 38_000_000,  "resources": 80,  "military": 40},
    "Mexico":        {"short_name": "MX", "flag": "🇲🇽", "population": 128_000_000, "resources": 60,  "military": 30},
    "France":        {"short_name": "FR", "flag": "🇫🇷", "population": 65_000_000,  "resources": 75,  "military": 50},
    "Germany":       {"short_name": "DE", "flag": "🇩🇪", "population": 83_000_000,  "resources": 90,  "military": 60},
    "Japan":         {"short_name": "JP", "flag": "🇯🇵", "population": 125_000_000, "resources": 85,  "military": 55},
    "Brazil":        {"short_name": "BR", "flag": "🇧🇷", "population": 214_000_000, "resources": 70,  "military": 45},
    "India":         {"short_name": "IN", "flag": "🇮🇳", "population": 1_400_000_000, "resources": 75, "military": 65},
    "China":         {"short_name": "CN", "flag": "🇨🇳", "population": 1_450_000_000, "resources": 95, "military": 80},
    "Russia":        {"short_name": "RU", "flag": "🇷🇺", "population": 144_000_000, "resources": 90,  "military": 75},
    "Australia":     {"short_name": "AU", "flag": "🇦🇺", "population": 26_000_000,  "resources": 80,  "military": 35},
    "United Kingdom":{"short_name": "UK", "flag": "🇬🇧", "population": 67_000_000,  "resources": 85,  "military": 55},
    "Italy":         {"short_name": "IT", "flag": "🇮🇹", "population": 59_000_000,  "resources": 70,  "military": 45},
    "Spain":         {"short_name": "ES", "flag": "🇪🇸", "population": 47_000_000,  "resources": 65,  "military": 40},
    "South Korea":   {"short_name": "KR", "flag": "🇰🇷", "population": 52_000_000,  "resources": 80,  "military": 55},
    "North Korea":   {"short_name": "KP", "flag": "🇰🇵", "population": 26_000_000,  "resources": 40,  "military": 50},
    "Indonesia":     {"short_name": "ID", "flag": "🇮🇩", "population": 275_000_000, "resources": 65,  "military": 40},
    "Saudi Arabia":  {"short_name": "SA", "flag": "🇸🇦", "population": 36_000_000,  "resources": 85,  "military": 50},
    "Iran":          {"short_name": "IR", "flag": "🇮🇷", "population": 88_000_000,  "resources": 60,  "military": 55},
    "Turkey":        {"short_name": "TR", "flag": "🇹🇷", "population": 85_000_000,  "resources": 65,  "military": 55},
    "Egypt":         {"short_name": "EG", "flag": "🇪🇬", "population": 105_000_000, "resources": 55,  "military": 45},
    "South Africa":  {"short_name": "ZA", "flag": "🇿🇦", "population": 60_000_000,  "resources": 60,  "military": 35},
    "Nigeria":       {"short_name": "NG", "flag": "🇳🇬", "population": 220_000_000, "resources": 50,  "military": 35},
    "Argentina":     {"short_name": "AR", "flag": "🇦🇷", "population": 46_000_000,  "resources": 60,  "military": 30},
    "Poland":        {"short_name": "PL", "flag": "🇵🇱", "population": 38_000_000,  "resources": 60,  "military": 40},
    "Ukraine":       {"short_name": "UA", "flag": "🇺🇦", "population": 41_000_000,  "resources": 45,  "military": 45},
    "Netherlands":   {"short_name": "NL", "flag": "🇳🇱", "population": 17_000_000,  "resources": 70,  "military": 30},
    "Sweden":        {"short_name": "SE", "flag": "🇸🇪", "population": 10_000_000,  "resources": 65,  "military": 25},
    "Israel":        {"short_name": "IL", "flag": "🇮🇱", "population": 9_000_000,   "resources": 75,  "military": 50},
    "Pakistan":      {"short_name": "PK", "flag": "🇵🇰", "population": 240_000_000, "resources": 50,  "military": 50},
    "Vietnam":       {"short_name": "VN", "flag": "🇻🇳", "population": 98_000_000,  "resources": 50,  "military": 35},
    "Thailand":      {"short_name": "TH", "flag": "🇹🇭", "population": 72_000_000,  "resources": 55,  "military": 30},
}

# Land/short-sea adjacency graph (stylized, not 100% geographically literal —
# built for a fun, connected map rather than a strict atlas).
ADJACENCY_EDGES = [
    ("United States", "Canada"),
    ("United States", "Mexico"),
    ("Mexico", "Brazil"),
    ("Brazil", "Argentina"),
    ("France", "Germany"),
    ("France", "United Kingdom"),
    ("France", "Spain"),
    ("France", "Italy"),
    ("Germany", "Russia"),
    ("Germany", "Poland"),
    ("Germany", "Netherlands"),
    ("Poland", "Ukraine"),
    ("Sweden", "Germany"),
    ("Russia", "China"),
    ("Russia", "India"),
    ("Russia", "Ukraine"),
    ("Russia", "North Korea"),
    ("China", "India"),
    ("China", "Japan"),
    ("China", "North Korea"),
    ("China", "Vietnam"),
    ("China", "Pakistan"),
    ("India", "Pakistan"),
    ("North Korea", "South Korea"),
    ("South Korea", "Japan"),
    ("Indonesia", "Vietnam"),
    ("Indonesia", "Australia"),
    ("Vietnam", "Thailand"),
    ("Thailand", "Indonesia"),
    ("Pakistan", "Iran"),
    ("Iran", "Turkey"),
    ("Iran", "Saudi Arabia"),
    ("Turkey", "Ukraine"),
    ("Turkey", "Egypt"),
    ("Saudi Arabia", "Egypt"),
    ("Egypt", "Israel"),
    ("South Africa", "Nigeria"),
]

# Continental groupings — territory names never change even after conquest,
# so this lookup stays valid no matter who currently owns a territory.
CONTINENTS = {
    "United States": "North America", "Canada": "North America", "Mexico": "North America",
    "Brazil": "South America", "Argentina": "South America",
    "France": "Europe", "Germany": "Europe", "United Kingdom": "Europe", "Italy": "Europe",
    "Spain": "Europe", "Poland": "Europe", "Ukraine": "Europe", "Netherlands": "Europe", "Sweden": "Europe",
    "Russia": "Asia", "China": "Asia", "Japan": "Asia", "India": "Asia", "South Korea": "Asia",
    "North Korea": "Asia", "Indonesia": "Asia", "Pakistan": "Asia", "Vietnam": "Asia", "Thailand": "Asia",
    "Saudi Arabia": "Middle East", "Iran": "Middle East", "Turkey": "Middle East", "Israel": "Middle East",
    "Egypt": "Africa", "South Africa": "Africa", "Nigeria": "Africa",
    "Australia": "Oceania",
}

RANDOM_EVENTS = [
    ("Bumper Harvest", "resources", 15, "Good harvests boost {name}'s resources!"),
    ("Economic Boom", "resources", 20, "An economic boom fills {name}'s coffers!"),
    ("Natural Disaster", "resources", -15, "A natural disaster strikes {name}, draining resources!"),
    ("Military Parade", "infantry", 5, "A show of force raises {name}'s infantry ranks!"),
    ("Civil Unrest", "resources", -10, "Civil unrest disrupts {name}'s economy!"),
    ("Trade Deal Signed", "resources", 10, "A lucrative trade deal boosts {name}'s resources!"),
    ("Tech Breakthrough", "air", 3, "A technological breakthrough grows {name}'s air force!"),
    ("Naval Expansion", "navy", 3, "A shipbuilding drive grows {name}'s navy!"),
]

# ----------------------------------------------------------------------------
# Ideology / politics system
# ----------------------------------------------------------------------------

IDEOLOGIES = {
    "democracy":  {"name": "Democracy",  "color": Col.CYAN},
    "communism":  {"name": "Communism",  "color": Col.RED},
    "fascism":    {"name": "Fascism",    "color": Col.GREY},
    "monarchism": {"name": "Monarchism", "color": Col.YELLOW},
    "neutral":    {"name": "Neutral",    "color": Col.WHITE},
}

# Starting government for each nation (flavor, not a hard simulation).
STARTING_IDEOLOGY = {
    "United States": "democracy", "Canada": "democracy", "Mexico": "democracy",
    "France": "democracy", "Germany": "democracy", "United Kingdom": "democracy",
    "Italy": "democracy", "Spain": "democracy", "Japan": "democracy", "South Korea": "democracy",
    "India": "democracy", "Brazil": "democracy", "Argentina": "democracy", "Poland": "democracy",
    "Netherlands": "democracy", "Sweden": "democracy", "Israel": "democracy", "Indonesia": "democracy",
    "Australia": "democracy", "Ukraine": "democracy", "South Africa": "democracy", "Nigeria": "democracy",
    "Thailand": "democracy",
    "China": "communism", "Russia": "communism", "Vietnam": "communism", "North Korea": "communism",
    "Saudi Arabia": "monarchism",
    "Iran": "monarchism", "Turkey": "neutral", "Egypt": "neutral", "Pakistan": "neutral",
}

FIRST_NAMES = ["Alex", "Maria", "Chen", "Ivan", "Fatima", "Kwame", "Yuki", "Omar", "Elena", "Raj",
               "Sofia", "Wei", "Amara", "Dmitri", "Leila", "Hiro", "Nadia", "Carlos", "Priya", "Anders"]
LAST_NAMES = ["Volkov", "Reyes", "Okafor", "Tanaka", "Kowalski", "Silva", "Haddad", "Nowak", "Meyer",
              "Andersson", "Kim", "Petrov", "Costa", "Rahman", "Larsson", "Fischer", "Diallo", "Rossi"]


class Leader:
    def __init__(self, name, ideology, approval=60):
        self.name = name
        self.ideology = ideology
        self.approval = approval

    def to_dict(self):
        return {"name": self.name, "ideology": self.ideology, "approval": self.approval}

    @classmethod
    def from_dict(cls, d):
        return cls(d["name"], d["ideology"], d["approval"])

    @classmethod
    def random(cls, ideology):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        return cls(name, ideology, approval=random.randint(45, 75))


# ----------------------------------------------------------------------------
# Decision events — numbered-choice events, mostly politics/ideology flavored
# ----------------------------------------------------------------------------

def _shift(country, ideology, amount):
    country.shift_ideology(ideology, amount)


DECISION_EVENTS = [
    {
        "id": "political_crisis",
        "title": "\U0001F4F0 Political Crisis",
        "condition": lambda g, c: c.rival_ideology_gap() >= 15,
        "describe": lambda g, c: (
            f"{IDEOLOGIES[c.leading_rival_ideology()]['name']} support has reached "
            f"{c.ideology_support[c.leading_rival_ideology()]:.0f}% in {c.name}. "
            f"The government ({IDEOLOGIES[c.government]['name']}) is growing uneasy."
        ),
        "options": [
            ("Crack down on the movement", lambda g, c: (
                _shift(c, c.leading_rival_ideology(), -12), _shift(c, c.government, 6),
                setattr(c, "stability", max(0, c.stability - 8)))),
            ("Allow the movement to grow", lambda g, c: (
                _shift(c, c.leading_rival_ideology(), 8),
                setattr(c, "stability", max(0, c.stability - 2)))),
            ("Attempt political reform", lambda g, c: (
                _shift(c, c.leading_rival_ideology(), -4), _shift(c, c.government, 2),
                setattr(c, "stability", min(100, c.stability + 6)))),
        ],
    },
    {
        "id": "economic_unrest",
        "title": "\U0001F4C9 Economic Unrest",
        "condition": lambda g, c: c.resources < 30 and c.stability < 55,
        "describe": lambda g, c: f"Falling resources have left {c.name} on edge. Stability: {c.stability:.0f}%.",
        "options": [
            ("Emergency spending (costs resources, boosts stability)", lambda g, c: (
                setattr(c, "resources", max(0, c.resources - 15)),
                setattr(c, "stability", min(100, c.stability + 10)))),
            ("Do nothing", lambda g, c: setattr(c, "stability", max(0, c.stability - 5))),
        ],
    },
    {
        "id": "war_weariness",
        "title": "\U0001F3F4 War Weariness",
        "condition": lambda g, c: c.stability < 40,
        "describe": lambda g, c: f"Prolonged strife has worn down {c.name}'s people. Stability: {c.stability:.0f}%.",
        "options": [
            ("Rally the nation (propaganda campaign)", lambda g, c: (
                setattr(c, "resources", max(0, c.resources - 10)),
                setattr(c, "stability", min(100, c.stability + 15)))),
            ("Let discontent simmer", lambda g, c: setattr(c, "stability", max(0, c.stability - 5))),
        ],
    },
]

# Unit system -------------------------------------------------------------
UNIT_TYPES = ["infantry", "navy", "air"]
UNIT_ICONS = {"infantry": "\U0001F396", "navy": "\u2693", "air": "\u2708", "nukes": "\u2622"}
BASE_POWER = {"infantry": 1.0, "navy": 1.4, "air": 1.8}
BUILD_COSTS = {"infantry": 2, "navy": 4, "air": 6, "nukes": 150}
# key counters value, e.g. air beats infantry
COUNTERS = {"air": "infantry", "infantry": "navy", "navy": "air"}

# Research / tech system ---------------------------------------------------
# RP = "research points". Countries passively generate a small trickle of RP
# each turn, and can invest resources for more. Some techs are gated behind
# prerequisites, most notably the Nuclear Program tech — you cannot build a
# nuke without it, so nukes can never be rushed turn one. RP trickles in
# passively every turn and can be boosted further by researching the
# Research Institutes / Advanced Research Labs techs below.
RESOURCES_PER_RP = 2          # cost to convert resources into RP via 'research invest'
TECH_TREE = {
    "research_institutes": {
        "name": "Research Institutes", "cost": 5, "prereq": [],
        "desc": "+1 research point every turn.",
    },
    "advanced_research": {
        "name": "Advanced Research Labs", "cost": 12, "prereq": ["research_institutes"],
        "desc": "+2 more research points every turn (3 total from these two techs).",
    },
    "industrialization": {
        "name": "Industrialization", "cost": 8, "prereq": [],
        "desc": "+25% resource income every turn.",
    },
    "motorized_infantry": {
        "name": "Motorized Infantry", "cost": 6, "prereq": [],
        "desc": "Infantry cost -1 resource, +0.2 combat power each.",
    },
    "naval_engineering": {
        "name": "Naval Engineering", "cost": 6, "prereq": [],
        "desc": "Navy cost -1 resource, +0.2 combat power each.",
    },
    "air_superiority": {
        "name": "Air Superiority", "cost": 8, "prereq": [],
        "desc": "+0.3 combat power per air unit.",
    },
    "fortifications": {
        "name": "Fortifications", "cost": 6, "prereq": [],
        "desc": "+15% defense power when defending your territory.",
    },
    "cyber_warfare": {
        "name": "Cyber Warfare", "cost": 10, "prereq": ["industrialization"],
        "desc": "+15% success chance on spying and sabotage.",
    },
    "nuclear_program": {
        "name": "Nuclear Program", "cost": 10, "prereq": ["industrialization", "motorized_infantry"],
        "desc": "Required before you can build any nuclear weapons.",
    },
    "icbm": {
        "name": "ICBM Technology", "cost": 16, "prereq": ["nuclear_program"],
        "desc": "Nukes can be launched anywhere without needing a navy.",
    },
    "radar_network": {
        "name": "Radar Network", "cost": 10, "prereq": ["air_superiority"],
        "desc": "+15% chance to intercept incoming nuclear strikes.",
    },
}

MAX_TURNS = 40
ECONOMIC_VICTORY_RESOURCES = 400
ECON_STREAK_NEEDED = 3
ALLIANCE_DOMINANCE_PCT = 0.60
ALLIANCE_STREAK_NEEDED = 3
DEFAULT_SAVE_FILE = "worldconqueror_save.json"

DIFFICULTIES = {
    "easy":   {"ai_aggression": 0.7, "player_start_bonus": 40},
    "normal": {"ai_aggression": 1.0, "player_start_bonus": 0},
    "hard":   {"ai_aggression": 1.35, "player_start_bonus": -20},
}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def build_adjacency(edges):
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    return adj


ADJACENCY = build_adjacency(ADJACENCY_EDGES)


# ----------------------------------------------------------------------------
# Core classes
# ----------------------------------------------------------------------------

class Country:
    def __init__(self, name, short_name, flag, population, resources,
                 units=None, is_player=False, territory=None, government="neutral"):
        self.name = name
        self.short_name = short_name
        self.flag = flag
        self.population = population
        self.resources = resources
        self.units = units if units is not None else {"infantry": 0, "navy": 0, "air": 0, "nukes": 0}
        self.territory = territory if territory is not None else {self.name}
        self.is_player = is_player
        self.alive = True
        self.allies = set()
        self.research_points = 0.0
        self.researched = set()

        # politics
        self.government = government
        self.stability = random.randint(55, 80)
        self.ideology_support = self._starting_support(government)
        self.leader = Leader.random(government)

    @staticmethod
    def _starting_support(government):
        support = {ideo: 0.0 for ideo in IDEOLOGIES}
        support[government] = 55.0
        remainder = 45.0
        others = [i for i in IDEOLOGIES if i != government]
        weights = [random.random() for _ in others]
        total_w = sum(weights) or 1
        for i, w in zip(others, weights):
            support[i] = remainder * (w / total_w)
        return support

    @classmethod
    def from_military_stat(cls, name, short_name, flag, population, resources, military,
                            is_player=False, government="neutral"):
        infantry = int(military * 0.6)
        navy = int(military * 0.25)
        air = max(0, military - infantry - navy)
        units = {"infantry": infantry, "navy": navy, "air": air, "nukes": 0}
        return cls(name, short_name, flag, population, resources, units, is_player, government=government)

    # -- politics -------------------------------------------------------------
    def shift_ideology(self, ideology, amount):
        if ideology not in self.ideology_support:
            return
        self.ideology_support[ideology] = max(0.0, self.ideology_support[ideology] + amount)
        total = sum(self.ideology_support.values())
        if total > 0:
            for k in self.ideology_support:
                self.ideology_support[k] = self.ideology_support[k] / total * 100.0

    def leading_rival_ideology(self):
        rivals = {k: v for k, v in self.ideology_support.items() if k != self.government}
        return max(rivals, key=rivals.get)

    def rival_ideology_gap(self):
        rival = self.leading_rival_ideology()
        return self.ideology_support[rival] - self.ideology_support[self.government]

    def can_have_civil_war(self):
        return len(self.territory) >= 2

    # -- derived stats -----------------------------------------------------
    @property
    def military(self):
        """Aggregate combat strength for display / scoring purposes."""
        return int(self.units["infantry"] * BASE_POWER["infantry"]
                    + self.units["navy"] * BASE_POWER["navy"]
                    + self.units["air"] * BASE_POWER["air"]
                    + self.units["nukes"] * 50)

    @property
    def power_score(self):
        return self.military * 1.2 + self.resources * 0.5 + len(self.territory) * 15

    def effective_power_against(self, defender_units):
        base = 0.0
        for u in UNIT_TYPES:
            per_unit = BASE_POWER[u]
            if u == "infantry" and self.has_tech("motorized_infantry"):
                per_unit += 0.2
            if u == "navy" and self.has_tech("naval_engineering"):
                per_unit += 0.2
            if u == "air" and self.has_tech("air_superiority"):
                per_unit += 0.3
            base += self.units[u] * per_unit
        bonus = 0.0
        for u in UNIT_TYPES:
            n = self.units[u]
            countered = COUNTERS.get(u)
            if countered and defender_units.get(countered, 0) > 0 and n > 0:
                bonus += n * BASE_POWER[u] * 0.5
        return base + bonus

    def has_tech(self, tech_id):
        return tech_id in self.researched

    # -- economy -------------------------------------------------------------
    def collect_income(self):
        income = max(1, int(self.resources * 0.08)) + len(self.territory) * 2
        if self.has_tech("industrialization"):
            income = int(income * 1.25)
        self.resources += income
        upkeep = max(1, int(self.military * 0.03))
        self.resources = max(0, self.resources - upkeep)
        rp_gain = 2 + len(self.territory) * 0.4
        if self.has_tech("research_institutes"):
            rp_gain += 1
        if self.has_tech("advanced_research"):
            rp_gain += 2
        self.research_points += rp_gain
        return income, upkeep, rp_gain

    def build_unit(self, unit_type, amount):
        if amount <= 0:
            return False, 0
        if unit_type == "nukes" and not self.has_tech("nuclear_program"):
            return False, -1  # -1 signals "needs research", not "too expensive"
        per_unit_cost = BUILD_COSTS[unit_type]
        if unit_type == "infantry" and self.has_tech("motorized_infantry"):
            per_unit_cost = max(1, per_unit_cost - 1)
        if unit_type == "navy" and self.has_tech("naval_engineering"):
            per_unit_cost = max(1, per_unit_cost - 1)
        cost = amount * per_unit_cost
        if cost > self.resources:
            return False, cost
        self.resources -= cost
        self.units[unit_type] += amount
        return True, cost

    def apply_losses(self, fraction):
        for u in UNIT_TYPES:
            self.units[u] = max(0, int(self.units[u] * (1 - fraction)))

    def available_techs(self):
        return [tid for tid, t in TECH_TREE.items()
                if tid not in self.researched and all(p in self.researched for p in t["prereq"])]

    def research_tech(self, tech_id):
        if tech_id not in TECH_TREE or tech_id in self.researched:
            return False
        tech = TECH_TREE[tech_id]
        if not all(p in self.researched for p in tech["prereq"]):
            return False
        if self.research_points < tech["cost"]:
            return False
        self.research_points -= tech["cost"]
        self.researched.add(tech_id)
        return True

    def form_nation(self, other):
        new_name = f"{self.name}-{other.name}"
        new_short_name = f"{self.short_name}-{other.short_name}"
        new_flag = f"{self.flag}{other.flag}"
        new_units = {u: self.units[u] + other.units[u] for u in ("infantry", "navy", "air", "nukes")}
        # the larger partner's government/ideology leads the merged nation
        dominant, minor = (self, other) if self.power_score >= other.power_score else (other, self)
        new_nation = Country(
            new_name, new_short_name, new_flag,
            self.population + other.population,
            self.resources + other.resources,
            new_units,
            is_player=self.is_player or other.is_player,
            territory=self.territory.union(other.territory),
            government=dominant.government,
        )
        new_nation.research_points = self.research_points + other.research_points
        new_nation.researched = self.researched | other.researched
        new_nation.stability = (self.stability + other.stability) // 2
        new_nation.leader = dominant.leader
        return new_nation

    def to_dict(self):
        return {
            "name": self.name, "short_name": self.short_name, "flag": self.flag,
            "population": self.population, "resources": self.resources,
            "units": self.units, "territory": list(self.territory),
            "is_player": self.is_player, "alive": self.alive,
            "allies": list(self.allies),
            "research_points": self.research_points, "researched": list(self.researched),
            "government": self.government, "stability": self.stability,
            "ideology_support": self.ideology_support, "leader": self.leader.to_dict(),
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls(d["name"], d["short_name"], d["flag"], d["population"], d["resources"],
                   dict(d["units"]), d["is_player"], set(d["territory"]),
                   government=d.get("government", "neutral"))
        obj.alive = d["alive"]
        obj.allies = set(d["allies"])
        obj.research_points = d.get("research_points", 0.0)
        obj.researched = set(d.get("researched", []))
        obj.stability = d.get("stability", 65)
        if "ideology_support" in d:
            obj.ideology_support = dict(d["ideology_support"])
        if "leader" in d:
            obj.leader = Leader.from_dict(d["leader"])
        return obj


# ----------------------------------------------------------------------------
# Game
# ----------------------------------------------------------------------------

class Game:
    def __init__(self):
        self.countries = {}
        self.player = None
        self.turn = 1
        self.max_turns = MAX_TURNS
        self.difficulty = "normal"
        self.pacts = {}          # frozenset({a,b}) -> expiry_turn
        self.grudges = defaultdict(lambda: defaultdict(float))  # holder -> target -> points
        self.player_intel = {}   # target name -> turn last spied
        self.econ_streak = 0
        self.alliance_streak = 0
        self.notify = NotificationCenter()
        self.world_events_buffer = []
        self.history = []  # list of (turn, text)
        self.event_cooldowns = {}

    def log_history(self, text):
        self.history.append((self.turn, text))

    # -- setup ----------------------------------------------------------------
    def main_menu(self):
        print_banner()
        if os.path.exists(DEFAULT_SAVE_FILE):
            choice = input("\nA saved game was found. (N)ew game or (L)oad? ").strip().lower()
            if choice.startswith("l"):
                if self.load_game(DEFAULT_SAVE_FILE):
                    return
                print("Could not load save, starting a new game instead.")
        self.setup()

    def choose_difficulty(self):
        print("\nDifficulty: (E)asy, (N)ormal, (H)ard")
        while True:
            d = input("Choose difficulty [N]: ").strip().lower() or "n"
            if d.startswith("e"):
                self.difficulty = "easy"
                break
            elif d.startswith("h"):
                self.difficulty = "hard"
                break
            else:
                self.difficulty = "normal"
                break

    def choose_turn_limit(self):
        print(f"\nHow many turns should the game last? (10-200, default {MAX_TURNS})")
        raw = input(f"Turn limit [{MAX_TURNS}]: ").strip()
        if not raw:
            self.max_turns = MAX_TURNS
            return
        try:
            n = int(raw)
            self.max_turns = clamp(n, 10, 200)
            if self.max_turns != n:
                print(c(f"Clamped to {self.max_turns}.", Col.YELLOW))
        except ValueError:
            print(c(f"Invalid number, using default of {MAX_TURNS}.", Col.YELLOW))
            self.max_turns = MAX_TURNS

    def setup(self):
        self.choose_difficulty()
        self.choose_turn_limit()

        for name, data in COUNTRIES_DATA.items():
            self.countries[name] = Country.from_military_stat(
                name, data["short_name"], data["flag"],
                data["population"], data["resources"], data["military"],
                government=STARTING_IDEOLOGY.get(name, "neutral"))

        print("\nAvailable countries:\n")
        self.print_country_table(list(self.countries.values()), fog=False)

        while self.player is None:
            choice = input("\nChoose your country: ").strip()
            if choice.lower() == "list":
                self.print_country_table(list(self.countries.values()), fog=False)
                continue
            match = self.find_country(choice)
            if match:
                self.player = match
                match.is_player = True
            else:
                print("Invalid country. Try again (type 'list' to see options).")

        bonus = DIFFICULTIES[self.difficulty]["player_start_bonus"]
        if bonus:
            self.player.resources = max(10, self.player.resources + bonus)

        print(c(f"\nYou are now leading {self.player.flag} {self.player.name}! Good luck.\n", Col.BOLD, Col.GREEN))
        time.sleep(0.3)

    def find_country(self, name):
        if name in self.countries:
            return self.countries[name]
        for cnt in self.countries.values():
            if cnt.short_name.lower() == name.lower() or cnt.name.lower() == name.lower():
                return cnt
        return None

    # -- geography ------------------------------------------------------------
    def territories_adjacent(self, t1, t2):
        return t2 in ADJACENCY.get(t1, set())

    def get_attackable(self, attacker):
        """Returns list of (target_country, territory_name, overseas_bool)."""
        results = []
        for other in self.countries.values():
            if other is attacker:
                continue
            if other.name in attacker.allies:
                continue
            for t in other.territory:
                adjacent = any(self.territories_adjacent(t, at) for at in attacker.territory)
                if adjacent:
                    results.append((other, t, False))
                elif attacker.units.get("navy", 0) > 0:
                    results.append((other, t, True))
        return results

    # -- display ----------------------------------------------------------------
    def fuzzed(self, value):
        spread = 0.25
        return int(value * random.uniform(1 - spread, 1 + spread))

    def display_stats(self, target, fog=True):
        """Returns (population, resources_str, military_str, known_bool)."""
        if not fog or target is self.player:
            return target.population, str(target.resources), str(target.military), True
        known = self.player_intel.get(target.name, -999) >= self.turn - 5
        if known:
            return target.population, str(target.resources), str(target.military), True
        return target.population, f"~{self.fuzzed(target.resources)}", f"~{self.fuzzed(target.military)}", False

    def ideology_bar(self, country, width=12):
        lines = []
        for ideo, info in IDEOLOGIES.items():
            pct = country.ideology_support.get(ideo, 0.0)
            filled = int(round(pct / 100 * width))
            bar = "\u2588" * filled + "\u2591" * (width - filled)
            marker = " (ruling)" if ideo == country.government else ""
            lines.append(f"    {info['name']:<11} {c(bar, info['color'])} {pct:5.1f}%{marker}")
        return lines

    def print_country_table(self, country_list, fog=True):
        print(f"{'Abbr':<6}{'Country':<22}{'Flag':<6}{'Pop':>15}{'Res':>10}{'Mil':>10}")
        for cnt in sorted(country_list, key=lambda x: -x.power_score):
            pop, res, mil, known = self.display_stats(cnt, fog=fog)
            tag = "" if (known or not fog) else " ?"
            print(f"{cnt.short_name:<6}{cnt.name:<22}{cnt.flag:<6}{pop:>15,}{res:>10}{mil + tag:>10}")

    def status(self):
        p = self.player
        print(c(f"\n--- {p.flag} {p.name} | Turn {self.turn}/{self.max_turns} | Difficulty: {self.difficulty} ---",
                Col.BOLD, Col.CYAN))
        print(f"  Population : {p.population:,}")
        print(f"  Resources  : {p.resources}")
        print(f"  Units      : infantry {p.units['infantry']}  navy {p.units['navy']}  "
              f"air {p.units['air']}  nukes {p.units['nukes']}")
        print(f"  Territory  : {', '.join(sorted(p.territory))}")
        gov_color = IDEOLOGIES[p.government]["color"]
        print(f"  Government : {c(IDEOLOGIES[p.government]['name'], gov_color)}  |  Stability: {p.stability:.0f}%")
        print(f"  Leader     : {p.leader.name} ({p.leader.ideology}) — Approval {p.leader.approval:.0f}%")
        print(f"  Allies     : {', '.join(sorted(p.allies)) if p.allies else 'None'}")
        active_pacts = self.active_pacts_for(p.name)
        print(f"  NAPs       : {', '.join(active_pacts) if active_pacts else 'None'}")
        techs = ', '.join(TECH_TREE[t]['name'] for t in sorted(p.researched)) if p.researched else 'None'
        print(f"  Research   : {p.research_points:.1f} RP  |  Researched: {techs}")
        print(f"  Power score: {p.power_score:.1f}")
        total_territories = sum(len(c.territory) for c in self.countries.values())
        my_share = (len(p.territory) + sum(len(self.countries[a].territory) for a in p.allies if a in self.countries)) / max(1, total_territories)
        print(f"  World territory controlled (you + allies): {my_share*100:.1f}%")
        print(f"  Nations remaining in the world: {len(self.countries)}")

    def world_status(self):
        print(c("\n=== World Standings ===", Col.BOLD, Col.YELLOW))
        self.print_country_table(list(self.countries.values()), fog=True)

    def world_ranking(self):
        countries = list(self.countries.values())
        print(c("\n=== World Power Ranking ===", Col.BOLD, Col.YELLOW))
        for i, cnt in enumerate(sorted(countries, key=lambda x: -x.power_score)[:10], 1):
            tag = " (YOU)" if cnt is self.player else ""
            print(f"  {i:>2}. {cnt.flag} {cnt.name:<22} {cnt.power_score:7.1f}{tag}")

        def top(label, key):
            print(c(f"\n  Top {label}:", Col.CYAN))
            for i, cnt in enumerate(sorted(countries, key=key, reverse=True)[:5], 1):
                print(f"    {i}. {cnt.flag} {cnt.short_name}")

        top("Military", lambda x: x.military)
        top("Resources", lambda x: x.resources)
        top("Population", lambda x: x.population)
        top("Research (techs unlocked)", lambda x: len(x.researched))

    def world_history(self):
        print(c("\n=== World History ===", Col.BOLD, Col.YELLOW))
        if not self.history:
            print("  Nothing notable has happened yet.")
            return
        for turn, text in self.history[-30:]:
            print(f"  Turn {turn:>3}: {text}")

    def active_pacts_for(self, name):
        result = []
        for pair, expiry in self.pacts.items():
            if name in pair:
                other = next(iter(pair - {name}))
                result.append(f"{other} (until turn {expiry})")
        return result

    def has_pact(self, a, b):
        return frozenset({a, b}) in self.pacts

    # -- player actions -----------------------------------------------------------
    def player_attack(self):
        options = self.get_attackable(self.player)
        if not options:
            print(c("No reachable targets. Build a navy to project power overseas, "
                    "or check if everyone nearby is your ally.", Col.YELLOW))
            return False

        by_country = defaultdict(list)
        for target, terr, overseas in options:
            by_country[target.name].append((terr, overseas))

        print("\nReachable targets:")
        for name, terrs in by_country.items():
            target = self.countries[name]
            pop, res, mil, known = self.display_stats(target)
            overseas_tag = " (navy required)" if all(o for _, o in terrs) else ""
            print(f"  {target.flag} {name} — territories: {', '.join(t for t, _ in terrs)}{overseas_tag}")

        name = input("\nAttack which country? ").strip()
        target = self.find_country(name)
        if not target or target.name not in by_country:
            print("Invalid or unreachable target.")
            return False

        terr_options = by_country[target.name]
        if len(terr_options) == 1:
            territory, overseas = terr_options[0]
        else:
            print(f"Which territory of {target.name}? {', '.join(t for t, _ in terr_options)}")
            tchoice = input("> ").strip()
            match = next((t for t, o in terr_options if t.lower() == tchoice.lower()), None)
            if not match:
                print("Invalid territory.")
                return False
            territory = match
            overseas = next(o for t, o in terr_options if t == territory)

        if target.name in self.player.allies:
            confirm = input(c(f"{target.name} is your ALLY! Betray them? (yes/no): ", Col.RED)).lower()
            if confirm != "yes":
                print("Attack cancelled.")
                return False
        if self.has_pact(self.player.name, target.name):
            confirm = input(c(f"You have a non-aggression pact with {target.name}! "
                               f"Break it and attack? (yes/no): ", Col.RED)).lower()
            if confirm != "yes":
                print("Attack cancelled.")
                return False

        self.resolve_attack(self.player, target, territory, overseas)
        return True

    def player_attack_continent(self):
        options = self.get_attackable(self.player)
        options = [(t, terr, ov) for (t, terr, ov) in options if not self.has_pact(self.player.name, t.name)]
        if not options:
            print(c("No reachable targets. Build a navy to project power overseas, "
                    "or check if everyone nearby is your ally or under pact.", Col.YELLOW))
            return False

        by_continent = defaultdict(list)
        for target, terr, overseas in options:
            by_continent[CONTINENTS.get(terr, "Unknown")].append((target, terr, overseas))

        print("\nContinents with reachable territory:")
        for cont, items in sorted(by_continent.items()):
            print(f"  {cont}: {len(items)} reachable territories")

        choice = input("\nLaunch a continental offensive against which continent? (enter to cancel): ").strip()
        if not choice:
            return False
        match = next((cont for cont in by_continent if cont.lower() == choice.lower()), None)
        if not match:
            print("Invalid continent.")
            return False

        targets = by_continent[match]
        print(f"\nThis will strike {len(targets)} territories across {match}:")
        for target, terr, overseas in targets:
            tag = " (overseas)" if overseas else ""
            print(f"  {target.flag} {terr} (held by {target.name}){tag}")

        multiplier = max(0.4, 1 / (len(targets) ** 0.5))
        print(c(f"\nSpreading your forces across {len(targets)} fronts reduces each attack's "
                f"power to about {multiplier * 100:.0f}%.", Col.YELLOW))
        confirm = input("Proceed with the continental offensive? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Offensive cancelled.")
            return False

        print(c(f"\n\U0001F310 Launching a continental offensive across {match}!\n", Col.BOLD, Col.RED))
        conquered = 0
        attempted = 0
        for target, terr, overseas in targets:
            current = self.countries.get(target.name)
            if not current or terr not in current.territory:
                continue  # already taken earlier this sweep, or eliminated
            if self.player.name not in self.countries:
                break  # extremely unlikely, but stop if the player somehow fell
            attempted += 1
            if self.resolve_attack(self.player, current, terr, overseas, atk_multiplier=multiplier):
                conquered += 1

        print(c(f"\nContinental offensive complete: {conquered}/{attempted} territories conquered.",
                Col.BOLD, Col.GREEN if conquered else Col.YELLOW))
        return attempted > 0

    def resolve_attack(self, attacker, defender, territory_name, overseas=False, verbose=True, atk_multiplier=1.0):
        was_ally = defender.name in attacker.allies
        had_pact = self.has_pact(attacker.name, defender.name)

        atk_power = attacker.effective_power_against(defender.units) * random.uniform(0.85, 1.2) * atk_multiplier
        if overseas:
            atk_power *= 0.85
        def_power = defender.effective_power_against(attacker.units) * random.uniform(0.85, 1.2) * 1.1
        if defender.has_tech("fortifications"):
            def_power *= 1.15

        if verbose:
            print(f"\n{c('⚔️  ' + attacker.flag + ' ' + attacker.name + ' attacks ' + defender.flag + ' ' + defender.name + ' for ' + territory_name + '!', Col.BOLD, Col.RED)}")
            print(f"   {attacker.name} attack power:  {atk_power:6.1f}")
            print(f"   {defender.name} defense power: {def_power:6.1f}")

        diff_ratio = (atk_power - def_power) / max(1.0, (atk_power + def_power))
        success_chance = clamp(0.5 + diff_ratio * 0.9, 0.08, 0.92)
        won = random.random() < success_chance

        loser_losses = random.uniform(0.12, 0.28)
        winner_losses = random.uniform(0.03, 0.12)

        if won:
            attacker.apply_losses(winner_losses)
            defender.apply_losses(loser_losses)
            fraction = 1.0 / max(1, len(defender.territory))
            attacker.population += int(defender.population * fraction)
            attacker.resources += int(defender.resources * fraction * 0.5)
            defender.population = int(defender.population * (1 - fraction))
            defender.resources = int(defender.resources * (1 - fraction))
            defender.territory.discard(territory_name)
            attacker.territory.add(territory_name)
            eliminated = not defender.territory
            if verbose:
                print(c(f"   \U0001F4A5 {attacker.flag} {attacker.name} conquers {territory_name}!", Col.GREEN, Col.BOLD))
            if eliminated:
                defender.alive = False
                if verbose:
                    print(c(f"   \U0001F480 {defender.flag} {defender.name} has been eliminated!", Col.RED, Col.BOLD))
                self.log_history(f"\U0001F480 {defender.flag} {defender.name} was eliminated by "
                                  f"{attacker.flag} {attacker.name}.")
            elif not verbose:
                self.world_events_buffer.append(
                    f"{attacker.flag} {attacker.short_name} conquered {territory_name} from {defender.flag} {defender.short_name}")
            if eliminated and not verbose:
                self.world_events_buffer.append(
                    f"\U0001F480 {defender.flag} {defender.name} was eliminated by {attacker.flag} {attacker.short_name}")
        else:
            attacker.apply_losses(loser_losses)
            defender.apply_losses(winner_losses)
            if verbose:
                print(c(f"   \U0001F6E1️  {attacker.name}'s attack on {territory_name} fails!", Col.YELLOW))
            elif random.random() < 0.3:  # don't buffer every single bounce, just some
                self.world_events_buffer.append(
                    f"\U0001F6E1️ {defender.flag} {defender.short_name} repelled {attacker.flag} {attacker.short_name}")

        # relationship fallout
        self.grudges[defender.name][attacker.name] += 15
        if was_ally:
            self.grudges[defender.name][attacker.name] += 40
            attacker.allies.discard(defender.name)
            defender.allies.discard(attacker.name)
        if had_pact:
            self.grudges[defender.name][attacker.name] += 25
            self.pacts.pop(frozenset({attacker.name, defender.name}), None)

        if self.player is not None and defender is self.player and attacker is not self.player:
            outcome_line = f"Lost {territory_name}!" if won else f"You held {territory_name}."
            self.notify.push("\u26A0\uFE0F  UNDER ATTACK", [f"{attacker.flag} {attacker.name} struck you.", outcome_line],
                              color=Col.RED)

        self.cleanup_after_change()
        return won

    def cleanup_after_change(self):
        dead = [name for name, cnt in self.countries.items() if not cnt.alive]
        for name in dead:
            del self.countries[name]
        valid = set(self.countries.keys())
        for cnt in self.countries.values():
            cnt.allies &= valid
        self.pacts = {pair: exp for pair, exp in self.pacts.items() if pair <= valid}

    def player_build(self):
        print(f"Unit costs (resources each): infantry {BUILD_COSTS['infantry']}, "
              f"navy {BUILD_COSTS['navy']}, air {BUILD_COSTS['air']}, nukes {BUILD_COSTS['nukes']}")
        if not self.player.has_tech("nuclear_program"):
            print(c("  (nukes require the 'Nuclear Program' tech — use the Research menu)", Col.DIM))
        utype = input("Build which unit? (infantry/navy/air/nukes, or enter to cancel): ").strip().lower()
        if not utype:
            return False
        if utype not in BUILD_COSTS:
            print("Invalid unit type.")
            return False
        try:
            amt = int(input(f"How many? (you have {self.player.resources} resources): "))
        except ValueError:
            print("Enter a number.")
            return False
        ok, cost = self.player.build_unit(utype, max(0, amt))
        if ok:
            print(c(f"Built {amt} {utype} for {cost} resources.", Col.GREEN))
            return True
        elif cost == -1:
            print(c("You need the 'Nuclear Program' tech before you can build nukes. "
                     "Use the Research menu.", Col.RED))
            return False
        else:
            print(c(f"Not enough resources! Needed {cost}, have {self.player.resources}.", Col.RED))
            return False

    def player_research(self):
        p = self.player
        print(c(f"\nResearch points: {p.research_points:.1f}", Col.CYAN))
        available = p.available_techs()
        if available:
            print("Available techs:")
            for tid in available:
                t = TECH_TREE[tid]
                prereq_str = f" (needs: {', '.join(TECH_TREE[x]['name'] for x in t['prereq'])})" if t["prereq"] else ""
                print(f"  {tid:<20} {t['name']:<22} cost {t['cost']:>3} RP  - {t['desc']}{prereq_str}")
        else:
            print("No techs currently available (everything researched or locked behind prereqs).")
        print(f"\nType a tech id to research it, 'invest' to convert {RESOURCES_PER_RP} resources -> 1 RP, "
              f"or press enter to cancel.")
        choice = input("> ").strip().lower()
        if not choice:
            return False
        if choice == "invest":
            try:
                amt = int(input(f"Invest how many resources? (you have {p.resources}): "))
            except ValueError:
                print("Enter a number.")
                return False
            amt = max(0, min(amt, p.resources))
            gained = amt // RESOURCES_PER_RP
            if gained <= 0:
                print(c("Not enough resources to convert.", Col.YELLOW))
                return False
            p.resources -= gained * RESOURCES_PER_RP
            p.research_points += gained
            print(c(f"Converted {gained * RESOURCES_PER_RP} resources into {gained} RP.", Col.GREEN))
            return True
        if p.research_tech(choice):
            print(c(f"\U0001F52C Researched {TECH_TREE[choice]['name']}!", Col.GREEN, Col.BOLD))
            return True
        else:
            print(c("Can't research that right now (missing prereqs or not enough RP).", Col.RED))
            return False

    def alliance_accept_chance(self, proposer, target):
        chance = 0.6
        avg_power = self.average_power(exclude=None)
        if proposer.power_score > avg_power * 1.8:
            chance -= 0.35  # wary of the leader
        chance -= min(0.4, self.grudges[target.name][proposer.name] * 0.01)
        if target.power_score < proposer.power_score * 0.6:
            chance += 0.1  # weak nations want protection
        return clamp(chance, 0.05, 0.95)

    def average_power(self, exclude=None):
        vals = [c.power_score for c in self.countries.values() if c is not exclude]
        return sum(vals) / len(vals) if vals else 1.0

    def player_form_alliance(self):
        candidates = [c for c in self.countries.values() if c is not self.player and c.name not in self.player.allies]
        if not candidates:
            print("No candidates available.")
            return False
        print("\nPossible allies:")
        self.print_country_table(candidates)
        name = input("Propose alliance to which country? (enter to cancel): ").strip()
        if not name:
            return False
        target = self.find_country(name)
        if not target or target is self.player:
            print("Invalid target.")
            return False
        chance = self.alliance_accept_chance(self.player, target)
        if random.random() < chance:
            self.player.allies.add(target.name)
            target.allies.add(self.player.name)
            print(c(f"\U0001F91D {target.flag} {target.name} accepts your alliance offer!", Col.GREEN))
        else:
            print(c(f"\u274C {target.flag} {target.name} rejects your alliance offer.", Col.RED))
        return True

    def player_pact(self):
        candidates = [c for c in self.countries.values()
                      if c is not self.player and not self.has_pact(self.player.name, c.name)]
        if not candidates:
            print("No candidates available.")
            return False
        print("\nPossible non-aggression pact partners:")
        self.print_country_table(candidates)
        name = input("Propose a non-aggression pact to which country? (enter to cancel): ").strip()
        if not name:
            return False
        target = self.find_country(name)
        if not target or target is self.player:
            print("Invalid target.")
            return False
        chance = clamp(self.alliance_accept_chance(self.player, target) + 0.15, 0.1, 0.97)
        if random.random() < chance:
            self.pacts[frozenset({self.player.name, target.name})] = self.turn + 8
            print(c(f"\U0001F4DC Non-aggression pact signed with {target.flag} {target.name} (8 turns).", Col.GREEN))
        else:
            print(c(f"\u274C {target.flag} {target.name} declines the pact.", Col.RED))
        return True

    def player_merge(self):
        if not self.player.allies:
            print("You have no allies to merge with.")
            return False
        print(f"Allies: {', '.join(sorted(self.player.allies))}")
        name = input("Merge with which ally to form a new nation? (enter to cancel): ").strip()
        if not name:
            return False
        target = self.find_country(name)
        if not target or target.name not in self.player.allies:
            print("Invalid ally.")
            return False
        new_nation = self.player.form_nation(target)
        print(c(f"\n\U0001F389 {self.player.flag} {self.player.name} and {target.flag} {target.name} "
                f"unite to form {new_nation.flag} {new_nation.name}!", Col.BOLD, Col.MAGENTA))
        new_nation.allies = (self.player.allies | target.allies) - {self.player.name, target.name}

        # migrate grudges, pacts, intel from old names to new name
        for old_name in (self.player.name, target.name):
            for holder in list(self.grudges.keys()):
                if old_name in self.grudges[holder]:
                    self.grudges[holder][new_nation.name] = max(
                        self.grudges[holder].get(new_nation.name, 0), self.grudges[holder].pop(old_name))
            self.pacts = {
                (frozenset((new_nation.name if n == old_name else n) for n in pair)): exp
                for pair, exp in self.pacts.items()
            }
            self.player_intel.pop(old_name, None)

        del self.countries[self.player.name]
        del self.countries[target.name]
        self.countries[new_nation.name] = new_nation
        self.player = new_nation
        self.cleanup_after_change()
        return True

    def player_spy(self):
        candidates = [c for c in self.countries.values() if c is not self.player]
        if not candidates:
            print("No one to spy on.")
            return False
        print("\nSpy on which nation?")
        for cnt in candidates:
            print(f"  {cnt.flag} {cnt.name}")
        name = input("> ").strip()
        if not name:
            return False
        target = self.find_country(name)
        if not target or target is self.player:
            print("Invalid target.")
            return False
        mode = input("Gather intel or attempt sabotage? (intel/sabotage): ").strip().lower()
        cyber_bonus = 0.15 if self.player.has_tech("cyber_warfare") else 0.0
        if mode.startswith("s"):
            cost = 25
            if self.player.resources < cost:
                print(c(f"Not enough resources (need {cost}).", Col.RED))
                return False
            self.player.resources -= cost
            if random.random() < 0.55 + cyber_bonus:
                loss = random.uniform(0.1, 0.2)
                target.apply_losses(loss)
                target.resources = max(0, int(target.resources * 0.85))
                print(c(f"\U0001F575️  Sabotage successful! {target.name}'s forces and resources take a hit.", Col.GREEN))
            else:
                self.grudges[target.name][self.player.name] += 30
                print(c(f"\u274C Sabotage failed and was traced back to you! {target.name} is furious.", Col.RED))
            return True
        else:
            cost = 15
            if self.player.resources < cost:
                print(c(f"Not enough resources (need {cost}).", Col.RED))
                return False
            self.player.resources -= cost
            if random.random() < 0.85 + cyber_bonus:
                self.player_intel[target.name] = self.turn
                print(c(f"\U0001F575️  Espionage successful! True stats for {target.name} revealed for 5 turns:", Col.GREEN))
                print(f"   Resources: {target.resources}  |  Military: {target.military}  "
                      f"(infantry {target.units['infantry']}, navy {target.units['navy']}, "
                      f"air {target.units['air']}, nukes {target.units['nukes']})")
            else:
                print(c("Your spies were caught and yielded nothing useful.", Col.YELLOW))
            return True

    def can_reach_with_nuke(self, attacker, defender):
        if attacker.has_tech("icbm"):
            return True
        if attacker.units.get("navy", 0) > 0:
            return True
        return any(self.territories_adjacent(t, at) for t in defender.territory for at in attacker.territory)

    def use_nuke(self, attacker, defender, verbose=True):
        if attacker.units["nukes"] < 1:
            return False
        attacker.units["nukes"] -= 1
        # air defenses can partially intercept
        intercept_chance = clamp(defender.units["air"] * 0.01, 0, 0.5)
        if defender.has_tech("radar_network"):
            intercept_chance = clamp(intercept_chance + 0.15, 0, 0.65)
        if random.random() < intercept_chance:
            if verbose:
                nuke_flash()
                print(c(f"\u2622 {defender.name}'s air defenses intercept the incoming warhead!", Col.CYAN))
            return True
        dmg = random.uniform(0.3, 0.45)
        defender.population = int(defender.population * (1 - dmg * 0.5))
        defender.resources = max(0, int(defender.resources * (1 - dmg)))
        defender.apply_losses(dmg)
        if verbose:
            nuke_flash()
            print_art(MUSHROOM_CLOUD)
            print(c(f"\u2622\u2622\u2622 {attacker.flag} {attacker.name} launches a NUCLEAR STRIKE on "
                    f"{defender.flag} {defender.name}! Devastating losses inflicted.", Col.BOLD, Col.RED))
        self.grudges[defender.name][attacker.name] += 60
        for cnt in self.countries.values():
            if cnt is not attacker:
                self.grudges[cnt.name][attacker.name] += 20  # world is horrified
        self.log_history(f"\u2622 {attacker.flag} {attacker.name} launched a nuclear strike on "
                          f"{defender.flag} {defender.name}.")
        if not defender.territory or defender.population <= 0:
            defender.alive = False
            self.log_history(f"\U0001F480 {defender.flag} {defender.name} was destroyed in the nuclear strike.")
        self.cleanup_after_change()
        return True

    def player_nuke(self):
        if self.player.units["nukes"] < 1:
            print(c("You have no nuclear weapons. Build some first (very expensive).", Col.YELLOW))
            return False
        candidates = [c for c in self.countries.values() if c is not self.player]
        if not candidates:
            return False
        print("\nPossible targets:")
        for cnt in candidates:
            print(f"  {cnt.flag} {cnt.name}")
        name = input("Launch a nuke at which nation? (enter to cancel): ").strip()
        if not name:
            return False
        target = self.find_country(name)
        if not target or target is self.player:
            print("Invalid target.")
            return False
        if not self.can_reach_with_nuke(self.player, target):
            print(c(f"You have no delivery method to reach {target.name} — you need a navy "
                     f"nearby, land adjacency, or the ICBM tech.", Col.YELLOW))
            return False
        confirm = input(c(f"Are you SURE you want to nuke {target.name}? This will make the "
                           f"world hate you. (yes/no): ", Col.RED)).lower()
        if confirm == "yes":
            self.use_nuke(self.player, target)
            self.cleanup_after_change()
            return True
        return False

    # -- AI turns -------------------------------------------------------------------
    def ai_turn(self, country):
        if country is self.player or country.name not in self.countries:
            return
        others = [c for c in self.countries.values() if c is not country]
        if not others:
            return

        aggression = DIFFICULTIES[self.difficulty]["ai_aggression"]
        avg_power = self.average_power()
        leader = max(self.countries.values(), key=lambda c: c.power_score)
        is_leader_runaway = leader.power_score > avg_power * 1.8

        # Desperation nuke
        if (country.units["nukes"] >= 1 and country.power_score < avg_power * 0.5
                and random.random() < 0.15 and self.can_reach_with_nuke(country, leader)):
            self.use_nuke(country, leader)
            return

        roll = random.random()

        # Diplomacy: alliance
        if roll < 0.12 and len(country.allies) < 2:
            pool = [c for c in others if c.name not in country.allies
                    and self.grudges[country.name][c.name] < 30]
            if pool:
                candidate = random.choice(pool)
                if candidate is self.player:
                    print(c(f"\n\U0001F4DC {country.flag} {country.name} proposes an alliance with you!", Col.CYAN))
                    choice = input("   Accept? (yes/no): ").strip().lower()
                    if choice == "yes":
                        country.allies.add(self.player.name)
                        self.player.allies.add(country.name)
                        print(c("   Alliance formed!", Col.GREEN))
                    else:
                        print("   You declined.")
                else:
                    if random.random() < self.alliance_accept_chance(country, candidate):
                        country.allies.add(candidate.name)
                        candidate.allies.add(country.name)
            return

        # Diplomacy: NAP
        if roll < 0.20:
            pool = [c for c in others if not self.has_pact(country.name, c.name) and c.name not in country.allies]
            if pool:
                candidate = random.choice(pool)
                if candidate is self.player:
                    print(c(f"\n\U0001F4DC {country.flag} {country.name} proposes a non-aggression pact with you!", Col.CYAN))
                    choice = input("   Accept? (yes/no): ").strip().lower()
                    if choice == "yes":
                        self.pacts[frozenset({country.name, self.player.name})] = self.turn + 8
                        print(c("   Pact signed!", Col.GREEN))
                    else:
                        print("   You declined.")
                elif random.random() < 0.5:
                    self.pacts[frozenset({country.name, candidate.name})] = self.turn + 8
            return

        # Research: invest resources into RP, then unlock whatever's available/affordable
        if roll < 0.32:
            if country.resources > 40:
                invest = min(country.resources - 20, RESOURCES_PER_RP * 6)
                gained = invest // RESOURCES_PER_RP
                if gained > 0:
                    country.resources -= gained * RESOURCES_PER_RP
                    country.research_points += gained
            available = country.available_techs()
            affordable = [t for t in available if TECH_TREE[t]["cost"] <= country.research_points]
            if affordable:
                # prefer economy/military techs early, nuclear program once wealthy
                priority = [t for t in affordable if t != "nuclear_program"] or affordable
                country.research_tech(random.choice(priority))
            return

        # Build up if weak
        if country.power_score < avg_power * 0.85 and country.resources > 20 and roll < 0.68:
            weights = {"infantry": 0.5, "navy": 0.25, "air": 0.25}
            if (country.has_tech("nuclear_program") and country.resources > 250
                    and country.units["nukes"] == 0 and random.random() < 0.15):
                country.build_unit("nukes", 1)
            else:
                utype = random.choices(list(weights), weights=list(weights.values()))[0]
                amt = max(1, int(country.resources * 0.3 / BUILD_COSTS[utype]))
                country.build_unit(utype, amt)
            return

        # Attack
        options = self.get_attackable(country)
        options = [(t, terr, ov) for (t, terr, ov) in options if not self.has_pact(country.name, t.name)]
        if not options:
            return

        def target_score(opt):
            target, _, _ = opt
            score = -target.power_score
            score += self.grudges[country.name][target.name] * 2
            if is_leader_runaway and target is leader and random.random() < 0.5 * aggression:
                score += 500
            return score

        options.sort(key=target_score, reverse=True)
        top_n = options[:max(1, len(options) // 2)] if len(options) > 1 else options
        target, territory, overseas = random.choice(top_n) if random.random() < 0.4 else options[0]

        if random.random() < 0.75 * aggression:
            involves_player = target is self.player  # country is never self.player here
            self.resolve_attack(country, target, territory, overseas, verbose=involves_player)

    # -- events -----------------------------------------------------------------
    def random_event(self):
        if random.random() > 0.35:
            return
        country = random.choice(list(self.countries.values()))
        title, stat, amount, template = random.choice(RANDOM_EVENTS)
        if stat == "resources":
            country.resources = max(0, country.resources + amount)
        else:
            country.units[stat] = max(0, country.units[stat] + amount)
        self.notify.push(f"\U0001F4F0 {title}", [template.format(name=f"{country.flag} {country.name}")],
                          color=Col.MAGENTA)

    # -- victory conditions -------------------------------------------------------
    def check_victory(self):
        if self.player.name not in self.countries:
            return "defeat"
        if len(self.countries) == 1:
            return "conquest"

        if self.player.resources >= ECONOMIC_VICTORY_RESOURCES:
            self.econ_streak += 1
        else:
            self.econ_streak = 0
        if self.econ_streak >= ECON_STREAK_NEEDED:
            return "economic"

        total_territories = sum(len(c.territory) for c in self.countries.values())
        my_territories = len(self.player.territory) + sum(
            len(self.countries[a].territory) for a in self.player.allies if a in self.countries)
        if total_territories and my_territories / total_territories >= ALLIANCE_DOMINANCE_PCT:
            self.alliance_streak += 1
        else:
            self.alliance_streak = 0
        if self.alliance_streak >= ALLIANCE_STREAK_NEEDED:
            return "alliance"

        return None

    # -- save / load ----------------------------------------------------------------
    def save_game(self, filename=DEFAULT_SAVE_FILE):
        data = {
            "turn": self.turn,
            "max_turns": self.max_turns,
            "difficulty": self.difficulty,
            "player_name": self.player.name,
            "countries": {n: c.to_dict() for n, c in self.countries.items()},
            "pacts": [[list(pair), exp] for pair, exp in self.pacts.items()],
            "grudges": {h: dict(t) for h, t in self.grudges.items()},
            "player_intel": self.player_intel,
            "econ_streak": self.econ_streak,
            "alliance_streak": self.alliance_streak,
            "history": self.history,
            "event_cooldowns": self.event_cooldowns,
        }
        with open(filename, "w") as f:
            json.dump(data, f)
        print(c(f"Game saved to {filename}.", Col.GREEN))

    def load_game(self, filename=DEFAULT_SAVE_FILE):
        try:
            with open(filename) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        self.turn = data["turn"]
        self.max_turns = data.get("max_turns", MAX_TURNS)
        self.difficulty = data["difficulty"]
        self.countries = {n: Country.from_dict(d) for n, d in data["countries"].items()}
        self.player = self.countries[data["player_name"]]
        self.pacts = {frozenset(pair): exp for pair, exp in data["pacts"]}
        self.grudges = defaultdict(lambda: defaultdict(float))
        for h, t in data["grudges"].items():
            self.grudges[h] = defaultdict(float, t)
        self.player_intel = data["player_intel"]
        self.econ_streak = data.get("econ_streak", 0)
        self.alliance_streak = data.get("alliance_streak", 0)
        self.history = [tuple(x) for x in data.get("history", [])]
        self.event_cooldowns = data.get("event_cooldowns", {})
        print(c(f"Game loaded from {filename}. Welcome back, leader of {self.player.name}.", Col.GREEN))
        return True

    # -- politics / ideology --------------------------------------------------
    def process_politics(self, country):
        for ideo in IDEOLOGIES:
            drift = random.uniform(-1.5, 1.5)
            if country.stability < 50 and ideo != country.government:
                drift += 1.0
            country.shift_ideology(ideo, drift)

        if country.stability < 60:
            country.stability = min(60, country.stability + 1)
        elif country.stability > 60:
            country.stability = max(60, country.stability - 0.5)

        # elections (democracies only, periodic)
        if country.government == "democracy" and self.turn % 6 == 0:
            rival = country.leading_rival_ideology()
            if (country.ideology_support[rival] > country.ideology_support[country.government]
                    and random.random() < 0.5):
                country.government = rival
                country.leader = Leader.random(rival)
                country.stability = min(100, country.stability + 10)
                msg = (f"{country.flag} {country.name} holds elections — {IDEOLOGIES[rival]['name']} wins! "
                       f"New leader: {country.leader.name}.")
                self.log_history(msg)
                self.notify.push("\U0001F5F3\uFE0F Election Result", [msg], color=Col.CYAN)
                return

        # coups (any government, only when unstable)
        if country.stability < 35:
            rival = country.leading_rival_ideology()
            if country.rival_ideology_gap() >= 20 and random.random() < 0.12:
                country.government = rival
                country.leader = Leader.random(rival)
                country.stability = min(100, country.stability + 15)
                msg = f"\u26A1 Coup in {country.name}! {IDEOLOGIES[rival]['name']} forces seize power."
                self.log_history(msg)
                self.notify.push("\u26A1 COUP", [msg], color=Col.RED)

    def check_civil_wars(self):
        for name in list(self.countries.keys()):
            country = self.countries.get(name)
            if not country or not country.can_have_civil_war():
                continue
            if country.stability < 30 and country.rival_ideology_gap() >= 35 and random.random() < 0.25:
                self.trigger_civil_war(country)

    def trigger_civil_war(self, country):
        rebel_ideology = country.leading_rival_ideology()
        territories = sorted(country.territory)
        rebel_territories = set(territories[::2])
        gov_territories = country.territory - rebel_territories
        if not rebel_territories or not gov_territories:
            return
        fraction = len(rebel_territories) / len(territories)

        base_name = f"{IDEOLOGIES[rebel_ideology]['name']} {country.name}"
        rebel_name = base_name
        suffix = 2
        while rebel_name in self.countries:
            rebel_name = f"{base_name} ({suffix})"
            suffix += 1

        rebel_units = {u: max(0, int(country.units[u] * fraction * 0.7)) for u in ("infantry", "navy", "air", "nukes")}
        for u in rebel_units:
            country.units[u] = max(0, country.units[u] - rebel_units[u])

        rebel = Country(
            rebel_name, country.short_name + "-R", country.flag,
            int(country.population * fraction), int(country.resources * fraction * 0.6),
            rebel_units, is_player=False, territory=rebel_territories, government=rebel_ideology,
        )
        country.population = int(country.population * (1 - fraction))
        country.resources = int(country.resources * (1 - fraction * 0.6))
        country.territory = gov_territories
        country.stability = min(100, country.stability + 20)
        country.ideology_support[rebel_ideology] = 5.0

        self.countries[rebel_name] = rebel
        self.grudges[country.name][rebel_name] = 200
        self.grudges[rebel_name][country.name] = 200

        msg = (f"\U0001F4A5 CIVIL WAR in {country.name}! {IDEOLOGIES[rebel_ideology]['name']} rebels "
               f"break away as {rebel.flag} {rebel_name}.")
        self.log_history(msg)
        self.notify.push("\U0001F4A5 CIVIL WAR", [msg], color=Col.RED)
        self.cleanup_after_change()

    def maybe_trigger_decision_event(self, country, interactive):
        for event in DECISION_EVENTS:
            key = f"{country.name}:{event['id']}"
            if self.turn - self.event_cooldowns.get(key, -999) < 5:
                continue
            if not event["condition"](self, country):
                continue
            if random.random() > 0.5:
                continue
            self.event_cooldowns[key] = self.turn
            if interactive:
                self.present_decision_event(event, country)
            else:
                label, effect = random.choice(event["options"])
                effect(self, country)
                self.log_history(f"{country.flag} {country.name}: {event['title']} \u2192 \"{label}\"")
            return

    def present_decision_event(self, event, country):
        print()
        print_popup([event["describe"](self, country)], title=event["title"], color=Col.MAGENTA)
        for i, (label, _) in enumerate(event["options"], 1):
            print(f"  [{i}] {label}")
        choice = input("> ").strip()
        try:
            idx = int(choice) - 1
            if idx < 0:
                raise ValueError
            label, effect = event["options"][idx]
        except (ValueError, IndexError):
            label, effect = event["options"][0]
            print(c("Invalid choice, defaulting to the first option.", Col.YELLOW))
        effect(self, country)
        self.log_history(f"You ({country.name}): {event['title']} \u2192 \"{label}\"")
        print(c(f"You chose: {label}", Col.GREEN))

    def run(self):
        self.main_menu()

        while True:
            outcome = self.check_victory()
            if outcome == "defeat":
                print()
                print_art(SKULL_ART)
                print(c("\U0001F480 GAME OVER — your nation has been conquered!", Col.RED, Col.BOLD))
                break
            if outcome == "conquest":
                print()
                print_art(TROPHY_ART)
                print(c(f"\U0001F3C6 VICTORY! {self.player.flag} {self.player.name} has conquered the entire world!",
                        Col.GREEN, Col.BOLD))
                break
            if outcome == "economic":
                print()
                print_art(TROPHY_ART)
                print(c(f"\U0001F3C6 ECONOMIC VICTORY! {self.player.name} built an unrivaled economy "
                        f"({self.player.resources} resources)!", Col.GREEN, Col.BOLD))
                break
            if outcome == "alliance":
                print()
                print_art(TROPHY_ART)
                print(c(f"\U0001F3C6 ALLIANCE VICTORY! {self.player.name} and its allies dominate "
                        f"the majority of the world's territory!", Col.GREEN, Col.BOLD))
                break
            if self.turn > self.max_turns:
                self.end_game_by_score()
                break

            self.status()

            income, upkeep, rp_gain = self.player.collect_income()
            self.notify.push("\U0001F4B0 Treasury Report", [
                f"Income:   +{income} resources",
                f"Upkeep:   -{upkeep} resources",
                f"Research: +{rp_gain:.1f} RP",
            ], color=Col.YELLOW)
            self.process_politics(self.player)
            self.random_event()
            self.notify.flush()
            self.maybe_trigger_decision_event(self.player, interactive=True)

            result = self.main_action_menu()

            if result == "exit":
                print("Thanks for playing!")
                break

            if self.player.name not in self.countries:
                continue  # player was just eliminated; loop will catch defeat

            # AI turns for everyone else
            ai_countries = [cnt for cnt in self.countries.values() if cnt is not self.player]
            random.shuffle(ai_countries)
            for cnt in ai_countries:
                cnt.collect_income()
                self.process_politics(cnt)
                self.maybe_trigger_decision_event(cnt, interactive=False)
                if cnt.name in self.countries and self.player.name in self.countries:
                    self.ai_turn(cnt)

            self.check_civil_wars()

            if self.world_events_buffer:
                self.notify.push("\U0001F30D World News", self.world_events_buffer[-10:], color=Col.MAGENTA)
                self.world_events_buffer.clear()
            self.notify.flush()

            # expire old pacts, decay grudges
            self.pacts = {pair: exp for pair, exp in self.pacts.items() if exp > self.turn}
            for holder in self.grudges:
                for target in list(self.grudges[holder].keys()):
                    self.grudges[holder][target] = max(0, self.grudges[holder][target] - 2)

            self.turn += 1

    # -- menu system ----------------------------------------------------------------
    def main_action_menu(self):
        """Shows the main menu and routes into submenus. Loops internally for
        view-only actions; returns 'exit' or None once a turn-consuming action
        (or an explicit exit) has happened."""
        while True:
            choice = menu_choice(f"MAIN MENU — Turn {self.turn}/{self.max_turns}", [
                ("1", "Overview"),
                ("2", "Military"),
                ("3", "Diplomacy"),
                ("4", "Politics"),
                ("5", "Research & Tech"),
                ("6", "Espionage"),
                ("7", "System"),
            ], allow_back=False)
            if choice is None:
                continue
            if choice == "1":
                self.overview_menu()
                continue
            elif choice == "2":
                if self.military_menu():
                    return None
                continue
            elif choice == "3":
                if self.diplomacy_menu():
                    return None
                continue
            elif choice == "4":
                if self.politics_menu():
                    return None
                continue
            elif choice == "5":
                if self.player_research():
                    return None
                continue
            elif choice == "6":
                if self.player_spy():
                    return None
                continue
            elif choice == "7":
                result = self.system_menu()
                if result == "exit":
                    return "exit"
                continue

    def overview_menu(self):
        while True:
            choice = menu_choice("OVERVIEW", [
                ("1", "My Status"),
                ("2", "World Standings"),
                ("3", "Diplomacy Overview (allies / pacts / grudges)"),
                ("4", "World Power Ranking"),
                ("5", "World History"),
            ])
            if choice is None:
                return
            if choice == "1":
                self.status()
            elif choice == "2":
                self.world_status()
            elif choice == "3":
                self.diplomacy_overview()
            elif choice == "4":
                self.world_ranking()
            elif choice == "5":
                self.world_history()

    def diplomacy_overview(self):
        p = self.player
        print(c("\n=== Diplomacy Overview ===", Col.BOLD, Col.CYAN))
        print(f"  Allies : {', '.join(sorted(p.allies)) if p.allies else 'None'}")
        active_pacts = self.active_pacts_for(p.name)
        print(f"  NAPs   : {', '.join(active_pacts) if active_pacts else 'None'}")
        my_grudges = self.grudges.get(p.name, {})
        held_against_me = {h: t[p.name] for h, t in self.grudges.items() if t.get(p.name, 0) > 5}
        if held_against_me:
            print("  Nations that hold a grudge against you:")
            for name, amt in sorted(held_against_me.items(), key=lambda kv: -kv[1]):
                if name in self.countries:
                    print(f"    {self.countries[name].flag} {name}: {amt:.0f}")
        else:
            print("  No one holds a significant grudge against you.")

    def politics_menu(self):
        """Returns True if a turn-consuming action happened."""
        while True:
            p = self.player
            print(c(f"\n=== {p.flag} {p.name} — Politics ===", Col.BOLD, Col.CYAN))
            print(f"  Government: {c(IDEOLOGIES[p.government]['name'], IDEOLOGIES[p.government]['color'])}"
                  f"  |  Stability: {p.stability:.0f}%")
            print(f"  Leader: {p.leader.name}  |  Approval: {p.leader.approval:.0f}%")
            print("  Ideology support:")
            for line in self.ideology_bar(p):
                print(line)
            choice = menu_choice("POLITICS", [
                ("1", "Campaign for your ideology (spend resources)"),
                ("2", "Suppress a rival ideology (spend resources)"),
            ])
            if choice is None:
                return False
            if choice == "1":
                if self.player_campaign():
                    return True
            elif choice == "2":
                if self.player_suppress():
                    return True

    def player_campaign(self):
        p = self.player
        cost = 20
        if p.resources < cost:
            print(c(f"Not enough resources (need {cost}).", Col.RED))
            return False
        confirm = input(f"Spend {cost} resources campaigning for "
                         f"{IDEOLOGIES[p.government]['name']}? (yes/no): ").strip().lower()
        if confirm != "yes":
            return False
        p.resources -= cost
        p.shift_ideology(p.government, random.uniform(6, 12))
        print(c(f"Campaign complete. {IDEOLOGIES[p.government]['name']} support is now "
                f"{p.ideology_support[p.government]:.1f}%.", Col.GREEN))
        return True

    def player_suppress(self):
        p = self.player
        rival = p.leading_rival_ideology()
        cost = 25
        if p.resources < cost:
            print(c(f"Not enough resources (need {cost}).", Col.RED))
            return False
        confirm = input(f"Spend {cost} resources suppressing {IDEOLOGIES[rival]['name']} "
                         f"({p.ideology_support[rival]:.1f}% support)? This may cost you "
                         f"stability. (yes/no): ").strip().lower()
        if confirm != "yes":
            return False
        p.resources -= cost
        p.shift_ideology(rival, -random.uniform(8, 14))
        p.stability = max(0, p.stability - random.uniform(2, 6))
        print(c(f"Suppression complete. {IDEOLOGIES[rival]['name']} support is now "
                f"{p.ideology_support[rival]:.1f}%. Stability: {p.stability:.0f}%.", Col.GREEN))
        return True

    def military_menu(self):
        """Returns True if a turn-consuming action happened."""
        while True:
            choice = menu_choice("MILITARY", [
                ("1", "Attack a Territory"),
                ("2", "Continental Offensive (attack all reachable in one continent)"),
                ("3", "Build Units"),
                ("4", "Launch Nuke"),
            ])
            if choice is None:
                return False
            if choice == "1":
                if self.player_attack():
                    return True
            elif choice == "2":
                if self.player_attack_continent():
                    return True
            elif choice == "3":
                if self.player_build():
                    return True
            elif choice == "4":
                if self.player_nuke():
                    return True

    def diplomacy_menu(self):
        """Returns True if a turn-consuming action happened."""
        while True:
            choice = menu_choice("DIPLOMACY", [
                ("1", "Propose Alliance"),
                ("2", "Propose Non-Aggression Pact"),
                ("3", "Merge With Ally"),
            ])
            if choice is None:
                return False
            if choice == "1":
                if self.player_form_alliance():
                    return True
            elif choice == "2":
                if self.player_pact():
                    return True
            elif choice == "3":
                if self.player_merge():
                    return True

    def system_menu(self):
        while True:
            choice = menu_choice("SYSTEM", [
                ("1", "Save Game"),
                ("2", "Help"),
                ("3", "Exit"),
            ])
            if choice is None:
                return None
            if choice == "1":
                self.save_game()
            elif choice == "2":
                self.print_help()
            elif choice == "3":
                confirm = input("Are you sure you want to exit? (yes/no): ").strip().lower()
                if confirm == "yes":
                    return "exit"

    def print_help(self):
        print(c("""
World Conqueror — quick guide

  Overview  - View your stats, world standings, diplomatic relationships,
              the world power ranking, and the history log
  Military  - Attack a single territory, launch a Continental Offensive against
              every reachable territory on one continent at once, build units,
              or launch a nuke
  Diplomacy - Propose alliances / pacts, or merge with an ally into one nation
  Politics  - View your ideology support and leader, campaign for your own
              ideology, or suppress a rival one
  Research  - Spend research points on techs, or convert resources into RP
  Espionage - Spy on a rival for intel, or attempt sabotage
  System    - Save your game, view this help, or exit

Combat needs land adjacency to the target, or a navy to invade overseas. A
Continental Offensive hits every reachable territory in one continent in a
single turn, but spreads your forces thin — expect reduced attack power per
target the more fronts you open at once.

Research points trickle in every turn automatically, and you can convert
spare resources into more. Research Institutes and Advanced Research Labs
boost your RP income further. Nukes require the 'Nuclear Program' tech
(Research menu) before you can build one, and ICBM tech before you can
launch one without a navy nearby.

Every nation has a government ideology (Democracy, Communism, Fascism,
Monarchism, or Neutral) and a support percentage for each ideology. Low
stability lets rival ideologies grow. Democracies can peacefully vote in a
new government via elections; unstable nations risk a coup. If a rival
ideology gets far enough ahead while stability collapses, the nation can
fracture in a civil war, splitting off a breakaway rebel nation you'll need
to deal with. Occasional decision events will ask you to choose how to
respond to political and economic crises.

Country abbreviations are shown in the 'Abbr' column of any table — you can
type either the full name or the abbreviation when choosing a country. You
can also set how many turns the game lasts when starting a new game.
""", Col.CYAN))

    def end_game_by_score(self):
        print(c(f"\n\u23F0 Turn limit ({self.max_turns}) reached! Final standings:", Col.YELLOW, Col.BOLD))
        self.world_status()
        ranked = sorted(self.countries.values(), key=lambda c: -c.power_score)
        winner = ranked[0]
        if winner is self.player:
            print(c(f"\n\U0001F3C6 You win! {self.player.flag} {self.player.name} is the world's leading power!",
                    Col.GREEN, Col.BOLD))
        else:
            print(f"\n{winner.flag} {winner.name} ends the game as the leading power.")
            print(f"You finished at rank {ranked.index(self.player) + 1} of {len(ranked)}.")


def print_banner():
    print(c("=" * 62, Col.CYAN))
    print(c("   \U0001F30D  W O R L D   C O N Q U E R O R  \U0001F30D", Col.BOLD, Col.CYAN))
    print("   Geography, unit types, diplomacy, espionage, and nukes.")
    print("   Build your economy, grow your military,")
    print("   forge alliances, and conquer the globe.")
    print(c("=" * 62, Col.CYAN))


def main():
    try:
        Game().run()
    except KeyboardInterrupt:
        print("\n\nGame interrupted. Goodbye!")
        sys.exit(0)
    except EOFError:
        print("\n\nInput stream ended. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
