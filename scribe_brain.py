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

import os
import queue
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
    "pelted": ["...", "Thou art cruel, my lord.",
               "Charming, sire. Truly.", "Was that needful, my lord?"],
}


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
