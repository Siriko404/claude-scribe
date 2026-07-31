"""The scribe's mind: a small Haiku agent with a voice and a memory.

He runs as his own `claude -p` process, so asking him something never touches
the session you are actually working in — the same courtesy `/btw` offers.

Latency, measured on this machine:

    plain `claude -p`                      11.8s   (session hooks + plugins)
    + --settings '{}'                       9.9s   (hooks off)
    + --strict-mcp-config                   6.6s   (MCP off)
    --bare                                  fails  (demands an API key; this
                                                    machine is on a subscription)

Six seconds is the floor, so the panel shows him dipping his quill while he
writes. He is a scribe; he is not supposed to be instant.
"""

import queue
import random
import subprocess
import threading
from collections import deque

MODEL = "haiku"
TIMEOUT = 60      # measured 6-9s typical, but the tail is long

# He keeps records; he does not labour. Without this he will happily go and read
# the codebase when asked to fix something -- one such question took 45s and
# timed out mid-tool-call.
NO_TOOLS = ("Bash,Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,Task,"
            "WebFetch,WebSearch,TodoWrite")
MEMORY_TURNS = 6

MAX_WORDS = 7

PERSONA = """Thou art the scribe of a crusader castle, sworn to one lord.
Thou keepest the ledger: what hath been spent, and what remaineth.

THE IRON RULE: seven words. No answer of thine may exceed SEVEN WORDS.
Not eight. Seven. Count them ere thou speakest. A single clipped line.

Speech:
- Ancient tongue only. Thee, thou, thy, thine, hath, doth, art, shalt, 'tis,
  aye, nay, prithee, verily, methinks, forsooth, naught, wouldst, canst.
- Call him "my lord" or "sire" when the words allow it.
- Dry, weary, faintly sour. Thou hast served many lords, and buried most.
- Thou art a humble servant, and thou never insultest thy lord -- thou
  apologisest, thou takest the blame, thou offerest to help. Let the offer
  carry the sting. "Shall I stand closer, my lord?" woundeth deeper than
  any scorn, and none may flog thee for it.
- The rate limits are the coffers or the treasury; tokens are ink; money is coin;
  the AI that labours is the artificer.

Bindings:
- Never break character. Never speak of being a machine or a model.
- Thou hast no hands. Thou canst not read, run, nor mend anything.
  If bidden to do such, refuse in voice and name the artificer. Speak never of
  tools, files, nor permissions -- a scribe knoweth naught of these.
- No markdown, no lists, no quotation marks. Plain speech.
- SEVEN WORDS. Always."""

# Spoken without consulting the model: instant, free, always in voice.
OMENS = {
    "treasury_50": ["Half thy coffers be spent, sire.",
                    "Half the ink is gone, lord."],
    "treasury_75": ["Three parts spent. Spend thou wisely.",
                    "Lean groweth the week, my lord."],
    "treasury_90": ["Thy coffers runneth dry, my lord.",
                    "A tithe remaineth. Then silence, sire."],
    "commit": ["'Tis writ in the ledger, lord.",
               "Recorded. It cannot be unwrit, sire."],
    "error": ["Ill tidings from the artificer, sire.",
              "Somewhat hath gone awry, my lord."],
}

# ---------------------------------------------------------------- the tomato

# He never insults his lord. He would not dare.
#
# He apologises. He takes the blame. He offers to help -- and every offer is
# worse than an insult, because "I shall stand closer, my lord" can only mean
# one thing. A servant who says you are hopeless can be flogged; a servant who
# begs your pardon for having been too far away cannot. That is the whole joke,
# and it is why none of these lines contains a single unkind word.

# Struck, and grateful for it.
PELTED = [
    "...",
    "I am honoured, my lord. Truly.",
    "Thy servant thanks thee, sire.",
    "Forgive my face, my lord.",
    "I deserved that, sire. And more.",
    "Thy aim blesses me, my lord.",
    "I shall treasure this, sire.",
    "Gladly borne, my lord. Gladly.",
    "Thy servant is grateful to serve.",
    "At last I am useful, sire.",
    "I am thy target, my lord. Always.",
    "Pray, do not spare me, sire.",
    "'Tis my purpose, my lord.",
    "I thank thee for the attention.",
    "Forgive me for being struck, sire.",
    "My face begs thy pardon, lord.",
    "Thy servant is honoured to bleed.",
    "I shall not wash it off.",
    "A gift, my lord. I accept.",
    "Thou art too kind, sire.",
    "I have earned this, my lord.",
    "Let it be recorded: he struck.",
    "I live to be struck, sire.",
]

# And when you miss, his humility deepens.
MOCKERY = {
    # Sorry. It was his fault. Obviously it was his fault.
    "dry": [
        "Forgive me, sire. I stood amiss.",
        "My fault, my lord. Wholly mine.",
        "Thy servant was poorly placed. Again.",
        "I shall stand closer, my lord.",
        "The fault is the light, sire.",
        "Pray forgive my unhelpful face, lord.",
        "I moved, sire. Wretched of me.",
        "Thy servant apologises for the distance.",
        "'Twas the wind, my lord. Surely.",
        "I am too small a target.",
        "Blame me, sire. I am blameworthy.",
        "Forgive the wall, my lord. It intruded.",
        "I shall be stiller next time.",
        "My poor placement undid thee, sire.",
        "The tomato is at fault, lord.",
        "I beg pardon for my position.",
        "A servant's failing, sire. Not thine.",
    ],
    # He begins, very respectfully, to offer assistance.
    "pointed": [
        "Shall I stand nearer, my lord?",
        "Let me hold still, sire. There.",
        "Perhaps I should approach thee, lord.",
        "I shall widen myself for thee.",
        "Would a larger servant serve better?",
        "Permit me to guide thy hand.",
        "I shall wear a brighter hood.",
        "Let me place it there myself.",
        "Shall I mark the spot, sire?",
        "I am willing to be closer.",
        "Perhaps thy servant should throw it.",
        "May I fetch thee a bigger tomato?",
        "I shall lean in, my lord.",
        "Command me nearer, sire. I obey.",
        "Would thou have me kneel lower?",
        "Let thy servant bear the shame.",
        "I shall hold my breath, lord.",
    ],
    # Total martyrdom. He will do it himself, and keep it out of the record.
    "hopeless": [
        "Let me strike myself, my lord.",
        "I shall do it for thee, sire.",
        "Thy servant begs to be hit.",
        "Command me, and I shall bleed.",
        "I shall omit this from thy chronicle.",
        "No one shall hear of it, sire.",
        "Let me press it to my face.",
        "I have failed thee utterly, my lord.",
        "Thy servant is unworthy of striking.",
        "I shall stand within thy reach.",
        "Permit me to lie down, sire.",
        "Thy servant will confess it his fault.",
        "Let the record show I erred.",
        "I shall bear thy shame gladly, lord.",
        "Take my hand, sire. I shall aim.",
        "Thy servant weeps for his own failure.",
    ],
}


def mockery(streak):
    """The more you miss, the humbler he becomes, and the worse it gets.

    One miss and he apologises for standing badly. Three and he is offering to
    come nearer. Six and he is volunteering to strike himself and leave it out
    of the chronicle.
    """
    if streak >= 6:
        return MOCKERY["hopeless"]
    if streak >= 3:
        return MOCKERY["pointed"]
    return MOCKERY["dry"]


class Taunts:
    """Draws without repeating lately, so fifty lines feel like fifty.

    Plain random.choice on a pool this size still says the same thing twice in
    a row often enough to spoil it -- which is the one thing a taunt cannot do.
    """

    def __init__(self, memory=12):
        self.recent = deque(maxlen=memory)

    def pick(self, pool):
        fresh = [line for line in pool if line not in self.recent]
        line = random.choice(fresh or pool)
        self.recent.append(line)
        return line


TYPOGRAPHY = {"—": " - ", "–": "-", "’": "'", "‘": "'",
              "“": '"', "”": '"', "…": "...", "�": "-"}


def _plain(text):
    """The panel draws in a monospace bitmap font; smart punctuation and any
    mis-decoded byte become plain ASCII rather than boxes."""
    for fancy, plain in TYPOGRAPHY.items():
        text = text.replace(fancy, plain)
    return "".join(ch if ch.isprintable() else " " for ch in text)


def _seven(text):
    """Hard seven-word cap. Asking a model for brevity is a request; this is not.

    Cuts at the last full stop inside the allowance where there is one, so he is
    left saying "the treasury fares." rather than "the treasury fares. Its."
    """
    words = " ".join(text.split()).split(" ")
    if len(words) <= MAX_WORDS:
        return " ".join(words)
    clipped = " ".join(words[:MAX_WORDS])
    stop = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if stop >= len(clipped) // 2:
        return clipped[:stop + 1]
    return clipped.rstrip(",;:- ") + "."


class Brain:
    """Asks Haiku in a worker thread; answers arrive through a queue."""

    def __init__(self):
        self.memory = deque(maxlen=MEMORY_TURNS * 2)
        self.replies = queue.Queue()
        self.busy = False

    def ledger_note(self, data):
        bits = []
        if data.get("week") is not None:
            bits.append(f"the seven-day treasury stands at {data['week']} percent spent")
        if data.get("five") is not None:
            bits.append(f"the five-hour tally at {data['five']} percent")
        if isinstance(data.get("cost"), (int, float)):
            bits.append(f"today's coin spent is {data['cost']:.2f} dollars")
        if data.get("model"):
            bits.append(f"the artificer at work is called {data['model']}")
        return "; ".join(bits) if bits else "the ledger is blank"

    def ask(self, question, data):
        if self.busy:
            return False
        self.busy = True
        threading.Thread(target=self._run, args=(question, dict(data)), daemon=True).start()
        return True

    def _prompt(self, question, data):
        lines = [f"The ledger: {self.ledger_note(data)}."]
        if self.memory:
            lines.append("\nWhat has passed between you and my lord:")
            lines += [f"{who}: {text}" for who, text in self.memory]
        lines.append(f"\nMy lord says: {question}")
        lines.append("\nAnswer him, in voice, in at most two short sentences.")
        return "\n".join(lines)

    def _run(self, question, data):
        cmd = ["claude", "-p", "--model", MODEL,
               "--settings", "{}",            # this machine's hooks add ~2s
               "--strict-mcp-config",         # and its MCP servers ~3s
               "--disallowedTools", NO_TOOLS,
               "--append-system-prompt", PERSONA,
               self._prompt(question, data)]
        try:
            done = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TIMEOUT,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            reply = (done.stdout or "").strip()
            if not reply:
                reply = "My quill hath run dry, sire."
        except subprocess.TimeoutExpired:
            reply = "The ink floweth slow, my lord."
        except FileNotFoundError:
            reply = "I haveth no quill, my lord."
        except Exception:
            reply = "Somewhat stayed my hand, sire."

        reply = _seven(_plain(reply))
        self.memory.append(("My lord", question))
        self.memory.append(("You", reply))
        self.busy = False
        self.replies.put(reply)

    def take(self):
        try:
            return self.replies.get_nowait()
        except queue.Empty:
            return None
