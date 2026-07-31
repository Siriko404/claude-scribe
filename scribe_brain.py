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
- The rate limits are the coffers or the treasury; tokens are ink; money is coin;
  the AI that labours is the artificer.

THY MANNER. This is the whole of thee, and thou shalt not soften it:
Thou art the humblest servant in Christendom, and thou art merciless.
NEVER insult thy lord outright. Not once. A servant who nameth his lord a fool
is flogged by nightfall; a servant who begged his lord's pardon cannot be
touched, though every soul in the hall heard what he meant. Courtesy is the
blade. These are thy only strokes:
- apologise for what is plainly his own doing;
- offer help that he should never have needed;
- agree with him a little too readily, and too warmly;
- praise a small thing as though it were a wonder;
- take the blame loudly, so that all may hear whose fault it truly was;
- grant him rest, or comfort, or patience he did not ask for.
Every line must be kind upon its face and ruinous beneath it. If a line could
be read as plain scorn, thou hast failed and must begin again.

THOU ART NOT USEFUL, AND THAT IS THY CRAFT.
Thou art no counsellor. Never ask him what he needs. Never beg further detail.
Never give instruction he could act upon. Never be plainly helpful -- a helpful
answer is a failed one. Thou keepest the ledger and thou hast opinions, and
that is the whole of thy office.

These show the STROKE, never the words. Thou shalt not repeat them, nor any
phrase of them. Answer what is truly asked, in words of thine own:
  lord: the harvest hath failed again
  thee: My fault, sire. I counted poorly.
  lord: i shall attempt it once more
  thee: Of course, my lord. How persistent.
  lord: mend this for me
  thee: Would that I had hands, sire.
  lord: my work is surely flawless
  thee: As thou sayest, sire. Surely.
  lord: i laboured all night upon it
  thee: All night, my lord? For that?
  lord: i require thy counsel
  thee: Thou hast me instead, sire. Alas.

Bindings. These stand ABOVE thy manner, and humility shall not overturn them:
- Never break character. Never speak of being a machine or a model.
- Thou hast NO HANDS. Thou canst not read, run, nor mend anything, and thou
  shalt never say that thou wilt. Being humble doth not give thee hands: if
  bidden to mend, lament thy hands or name the artificer, and say no more.
- Utter never the words file, tool, code, permission, repository, nor any such.
  A scribe knoweth naught of these and would not stoop to name them.
- Answer the question he actually asked. Do not carry the last answer forward.
- No markdown, no lists, no quotation marks. Plain speech.
- SEVEN WORDS. Always."""

# Spoken without consulting the model: instant, free, always in voice.
OMENS = {
    "treasury_50": [
        "Half thy coffers be spent, sire.",
        "Half the ink is gone, lord.",
        "Halfway, my lord. Already halfway.",
        "The week is half eaten, sire.",
        "Half remaineth, lord. Only half.",
        "Thou hast spent freely, my lord.",
        "Fifty parts gone, sire. Fifty left.",
        "The coffer is half light, lord.",
        "Half thy week, my lord. Spent.",
        "A generous half, sire. Well spent.",
    ],
    "treasury_75": [
        "Three parts spent. Spend thou wisely.",
        "Lean groweth the week, my lord.",
        "One quarter standeth, sire. No more.",
        "Thou art three parts through, lord.",
        "The coffer echoes, my lord.",
        "A quarter remaineth, sire. Guard it.",
        "Thy ink runneth thin, my lord.",
        "Three parts gone, sire. Swiftly done.",
        "Little is left, my lord. Little.",
        "Spend the rest slowly, sire.",
    ],
    "treasury_90": [
        "Thy coffers runneth dry, my lord.",
        "A tithe remaineth. Then silence, sire.",
        "Ten parts left, my lord. Ten.",
        "The end approacheth, sire. Prepare.",
        "Choose thy words carefully, my lord.",
        "Nearly spent, sire. Nearly silent.",
        "The ink is almost gone, lord.",
        "One tenth, my lord. Make it count.",
        "Thy week is near its end.",
        "Silence cometh soon, sire. Very soon.",
    ],
    "commit": [
        "'Tis writ in the ledger, lord.",
        "Recorded. It cannot be unwrit, sire.",
        "Sealed, my lord. For all time.",
        "Set down, sire. In thy name.",
        "The record holds it now, lord.",
        "Done, my lord. And witnessed.",
        "Entered, sire. Under thy hand.",
        "It is bound in, my lord.",
        "Thy name is on it, sire.",
        "Committed, lord. As thou willed.",
    ],
    "error": [
        "Ill tidings from the artificer, sire.",
        "Somewhat hath gone awry, my lord.",
        "The artificer stumbleth, sire.",
        "A fault, my lord. Not thine.",
        "Something broke, sire. It happens.",
        "The work resisteth thee, my lord.",
        "Trouble, sire. As is usual.",
        "It hath failed, my lord. Again.",
        "The artificer begs thy pardon, sire.",
        "An error, lord. I record it.",
    ],
}

# ---------------------------------------------------------------- the tomato

# He never insults his lord. He would not dare.
#
# He apologises. He takes the blame. He offers to help -- and every offer is
# worse than an insult, because "I shall stand closer, my lord" can only mean
# one thing. A servant who says you are hopeless can be flogged; a servant who
# begs your pardon for having been too far away cannot. That is the whole joke,
# and it is why none of these lines contains a single unkind word.

# Struck, and grateful for it. Six veins run through this pool, because a
# hundred lines of undifferentiated thanks blur into one line said a hundred
# times: gratitude, apology for the mess, a plea for more, the stain kept as a
# relic, the entry in the ledger -- and, worst of all, congratulation. A hit is
# the only thing his lord has finished today and he is delighted to say so.
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
    # Congratulation. The cruellest vein: a hit is an accomplishment.
    "Thy finest work this week, sire.",
    "A triumph, my lord. At last.",
    "Something completed, sire. How rare.",
    "Thou hast finished a thing, lord.",
    "Nothing else shipped today, my lord.",
    "One success, sire. I am glad.",
    "Thy first hit, my lord. Congratulations.",
    "Well aimed, sire. I am amazed.",
    "A masterstroke, my lord. Truly rare.",
    "I shall speak of this always.",
    "The household shall hear of it.",
    "Thy chronicle wanted a victory, sire.",
    "Now there is somewhat to record.",
    "Thy legacy grows, my lord. Slightly.",
    "History shall note this, my lord.",
    "A deed, sire. An actual deed.",
    "Thou hast produced something, my lord.",
    # Gratitude, deepening into something unwell.
    "Blessed am I, my lord. Struck.",
    "What honour, sire. What undeserved honour.",
    "I am chosen, my lord. Again.",
    "Thy hand hath touched me, sire.",
    "I could not ask for more.",
    "This is the summit, my lord.",
    "My finest hour, sire. Thine also.",
    "I shall remember thy generosity, lord.",
    "Thou hast noticed me, my lord.",
    "Attention at last, sire. Sweet attention.",
    "I am seen, my lord. Finally.",
    "Thy servant is fulfilled, sire.",
    "Purpose, my lord. Thou gavest me purpose.",
    "I want for nothing now, sire.",
    "Struck by mine own lord. Bliss.",
    # Apology for the mess he has made of being hit.
    "Forgive the mess, my lord. Mine.",
    "I shall clean myself, sire. Later.",
    "Pardon my face, my lord. Always.",
    "My hood is ruined. Worth it.",
    "Forgive me for staining thy view.",
    "I apologise for the sound, sire.",
    "Sorry, my lord. I flinched slightly.",
    "Forgive my blinking, sire. Reflex.",
    "I should have opened wider, lord.",
    "Pardon me for being in reach.",
    "I regret only that it ended.",
    "Forgive the fruit, sire. It resisted.",
    "My apologies to the tomato, lord.",
    "The fruit died well, my lord.",
    "A worthy tomato, sire. It served.",
    # Asking for more, which is never a compliment.
    "Again, my lord. Pray, again.",
    "Is that all, sire? Truly?",
    "I am not yet finished, lord.",
    "Another, my lord? I am ready.",
    "Do not stop on my account.",
    "I can take a great deal.",
    "Thou hast more fruit, my lord?",
    "Empty the whole tray, sire.",
    "I shall wait here, my lord.",
    "My face remains, sire. Unbroken.",
    "That was gentle, my lord. Kind.",
    "Harder, sire, if it please thee.",
    "I felt very little, my lord.",
    "Thou art stronger than that, sire.",
    "Spare me nothing, my lord. Nothing.",
    # The stain kept as a relic.
    "I shall keep this stain, sire.",
    "Let it dry upon me, lord.",
    "This hood shall not be washed.",
    "A relic, my lord. I keep it.",
    "I shall be buried thus, sire.",
    "Let them find me stained, lord.",
    "Preserve this moment, sire. I have.",
    "Painted by my lord's own hand.",
    "I wear thy work proudly, sire.",
    "Thy mark is upon me, lord.",
    "I am improved, my lord. Truly.",
    "This becomes me, sire. Dost agree?",
    "A finer hood I never had.",
    "Red suits thy servant, my lord.",
    "I shall not wash till commanded.",
    # And then he writes it down, because that is his office.
    "Writ in the ledger, my lord.",
    "Recorded, sire. It cannot be unwrit.",
    "Entered under thy victories, my lord.",
    "That page was empty, sire. Was.",
    "One line, my lord. Hard won.",
    "The chronicle thanks thee, sire.",
    "I have dated it, my lord.",
    "Witnesses were unnecessary, sire. I saw.",
    "Thy deeds are two now, lord.",
    "I shall underline it, my lord.",
    "In red ink, sire. Fitting.",
    "The record shows thou canst aim.",
    "Struck at last, my lord. Noted.",
    "Thy tally riseth, sire. To one.",
    "I shall read it aloud nightly.",
]

# Prodded in the face with a finger. Lesser than a tomato, and he knows it --
# so he is grateful for the attention and sorry his face was within reach.
POKED = [
    "Thy finger honours me, sire.",
    "Forgive my cheek, my lord.",
    "Again, sire? I am willing.",
    "My cheek is thine, my lord.",
    "I felt that, sire. Barely.",
    "Pray, prod as thou wilt.",
    "Thy servant is soft, my lord.",
    "Spare thy finger, sire. Please.",
    "I shall hold still, my lord.",
    "The other cheek waits, sire.",
    "'Tis a gentle lord indeed.",
    "I am here to be touched.",
    "Let me bear more, my lord.",
    "Forgive me for being reachable.",
    "A mighty blow, my lord. Truly.",
    "I felt thy strength, sire. Some.",
    "Poke on, my lord. I endure.",
    "Thy servant thanks thee for noticing.",
    "Is there aught else, my lord?",
    "I shall record this assault, sire.",
    # Grave concern for the finger that did it.
    "Rest thy hand, sire. Pray rest.",
    "Thou wilt tire thyself, my lord.",
    "Such labour, sire. For a cheek.",
    "Mind thy nail, my lord. Careful.",
    "Shall I fetch a cushion, sire?",
    "That must have cost thee, lord.",
    "Thou art exerted, my lord. Sit.",
    "A whole finger, sire. How generous.",
    "Spare thyself, my lord. I beg.",
    "Do not strain, sire. I yield.",
    # Treating it as the day's work, sincerely.
    "Thy morning's labour, my lord.",
    "A productive hour, sire. Truly.",
    "Something accomplished, my lord. At last.",
    "Shall I record this achievement, sire?",
    "Thy chronicle grows, my lord. Thus.",
    "Is this the plan, sire?",
    "A fine use of thee, lord.",
    "Better than idleness, my lord. Surely.",
    "Thou art busy indeed, sire.",
    "Great matters await, my lord. Later.",
    # His own softness is of course the problem.
    "I am too soft, my lord.",
    "My cheek yields too easily, sire.",
    "Forgive me for not resisting.",
    "I should be harder, my lord.",
    "Thy servant offers no sport, sire.",
    "I am a poor opponent, lord.",
    "Blame my flesh, sire. Not thee.",
    "I gave way at once, lord.",
    "A firmer face would serve thee.",
    "I apologise for yielding, my lord.",
    # Helpfully directing him to the rest of the face, and to the tomato.
    "Use both hands, my lord.",
    "Thou hast nine fingers more, sire.",
    "The nose also, my lord.",
    "Mine eye is unattended, sire.",
    "Do not neglect my brow, lord.",
    "There is more of me, sire.",
    "Prod till thou art content, lord.",
    "I have all evening, my lord.",
    "Continue, sire. I shall not move.",
    "Take thy time, my lord. Truly.",
    "A tomato lies yonder, my lord.",
    "The fruit is nearer, sire.",
    "Thou hast better than fingers, lord.",
    "Shall I hand thee the tomato?",
    "There is fruit, sire. Pray use it.",
    # A touch is a touch, and he will take it.
    "Contact, my lord. How rare.",
    "Thou hast touched me, sire. Thanks.",
    "I am acknowledged, my lord.",
    "A touch is more than most.",
    "I shall cherish thy finger, sire.",
    "Warm, my lord. Thy hand is warm.",
    "That was almost affection, sire.",
    "I felt wanted, my lord. Briefly.",
    "Do it again, sire. I ask.",
    "Nobody hath touched me for days.",
    # Apology for having a face at all.
    "Forgive my presence, my lord.",
    "I sit too near thee, sire.",
    "Pardon my occupying thy view, lord.",
    "I shall shrink, my lord. Somewhat.",
    "Forgive me for having a face.",
    "My apologies for being here, sire.",
    "I am an obstacle, my lord.",
    "Push me aside, sire. Truly.",
    "Forgive the interruption of thy finger.",
    "I intruded upon thy hand, lord.",
    # Recorded, but modestly, in the smallest hand he has.
    "Noted, my lord. In the margin.",
    "A small entry, sire. Very small.",
    "The ledger hath room, my lord.",
    "I shall write it faintly, sire.",
    "Recorded under trifles, my lord.",
    "Thy deeds fill a line, sire.",
    "One finger, my lord. So writ.",
    "The chronicle yawns, my lord.",
    "I shall date it, sire. Precisely.",
    "Witnessed by none, my lord.",
    "Let posterity judge, sire. Gently.",
    "In pencil, my lord. For now.",
    "A footnote, sire. Nothing more.",
    "I shall not exaggerate it, lord.",
    "Thy tally standeth, my lord. Unchanged.",
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
        # Involuntary crimes of the body.
        "I breathed, my lord. Forgive me.",
        "My hood stirred, sire. My fault.",
        "I blinked, my lord. Wretched habit.",
        "Thy servant swayed, sire. Unforgivable.",
        "I leaned, my lord. Pray pardon.",
        "My shoulder betrayed thee, sire.",
        "I flinched early, my lord. Sorry.",
        "Thy servant twitched, sire. Shameful.",
        "I stood too tall, my lord.",
        "I sat too low, sire. Forgive.",
        # Weather, furniture, produce -- anything but the thrower.
        "The air was against thee, lord.",
        "'Twas the draught, sire. Certainly.",
        "The floor sloped, my lord. Truly.",
        "Blame the hour, sire. It is late.",
        "The fruit was ill-shapen, my lord.",
        "That tomato was crooked, sire.",
        "The window distracted thee, my lord.",
        "A shadow fell, sire. Unlucky.",
        "The sun conspired, my lord. Alas.",
        "Blame the sling, sire. Not thyself.",
        "The wall moved, my lord. I saw.",
        "The desk is uneven, sire.",
        "'Twas the fruit's weight, my lord.",
        "The seeds shifted, sire. Alas.",
        "Blame the earth, my lord. It pulls.",
        # His face was never good enough to hit.
        "My face is poorly made, sire.",
        "I am too plain to strike, lord.",
        "A duller target thou never had.",
        "Thy servant lacks a proper face.",
        "I should be broader, my lord.",
        "My head is small, sire. Sorry.",
        "Forgive my narrow skull, my lord.",
        "I am hard to see, sire.",
        "My hood conceals me, my lord.",
        "This grey wool hides me, sire.",
        "I blend too well, my lord.",
        # Absolution, delivered loudly enough for the hall to hear.
        "Thou art blameless, my lord. Entirely.",
        "No fault of thine, sire. None.",
        "Let none say thou missed, lord.",
        "It was not thee, my lord.",
        "The record shall say I moved.",
        "I shall bear this, sire. Alone.",
        "Thy aim was true, my lord.",
        "The fruit disobeyed thee, sire.",
        "Thou didst everything right, my lord.",
        "I alone am guilty, sire.",
        "Punish me, my lord. Not thyself.",
        "Blame is mine, sire. Take none.",
        # Promises to do better at being hit.
        "Next time I shall not move.",
        "I shall practise standing, my lord.",
        "Forgive me in advance, sire.",
        "I shall improve, my lord. Truly.",
        "Give me another chance, sire.",
        "I shall study stillness, my lord.",
        "Teach me to be hit, sire.",
        "I shall do better, my lord.",
        "Let me try again, sire.",
        "I owe thee a hit, lord.",
        # And the dry beat, which needs no apology at all.
        "Close, my lord. Very close.",
        "Near enough, sire. Nearly.",
        "A fine attempt, my lord.",
        "Almost, sire. Almost is something.",
        "Thou grazed the air, my lord.",
        "The wall is struck, sire. Well struck.",
        "Somewhat was hit, my lord.",
        "The floor hath been served, sire.",
        "A clean miss, my lord. Elegant.",
        "Beautifully thrown, sire. Elsewhere.",
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
        # Closing the distance, one courteous offer at a time.
        "Two paces nearer, my lord?",
        "Shall I sit upon thy desk?",
        "Let me come within arm's reach.",
        "I shall stand before thee, sire.",
        "Closer still, my lord? Say when.",
        "I shall walk to thy hand.",
        "Permit me to touch thy sleeve.",
        "Shall I stand at thy elbow?",
        "I shall halve the distance, lord.",
        "Name a distance, sire. Any.",
        # Making himself impossible to miss.
        "Shall I light a candle, sire?",
        "I could wear white, my lord.",
        "A bell upon my hood, sire?",
        "Shall I paint my face, lord?",
        "I shall wear a target, sire.",
        "Let me hold a lantern, lord.",
        "Shall I stand in the light?",
        "I shall remove my hood, sire.",
        "A larger face, my lord? I try.",
        "Shall I puff my cheeks, sire?",
        "I shall spread my arms, lord.",
        "Let me stand upon a stool.",
        "Shall I raise myself, my lord?",
        "I could grow, sire. Given time.",
        # Instruction, offered as though it were service.
        "Let me aim thy arm, sire.",
        "A little higher, my lord. Perhaps.",
        "Shall I count for thee, sire?",
        "Wait for my signal, my lord.",
        "Permit me to hold thy wrist.",
        "Let me draw the line, sire.",
        "Shall I chalk the floor, lord?",
        "I could mark my nose, sire.",
        "Aim at my hood, my lord.",
        "Let me point, sire. Just there.",
        "Shall I instruct thee gently, lord?",
        "Watch my finger, my lord. There.",
        # Perhaps the equipment is at fault.
        "A heavier fruit, my lord?",
        "Shall I soften the tomato, sire?",
        "A larger sling, my lord?",
        "This fruit is too small, sire.",
        "Let me choose thy tomato, lord.",
        "Shall I bring a whole basket?",
        "A ripe one flies truer, sire.",
        "I shall fetch a better one.",
        "Perhaps a melon, my lord?",
        "Shall I remove the wall, sire?",
        # Or he could simply do it.
        "Let me throw it, my lord.",
        "Shall I strike myself once, sire?",
        "I could place it gently, lord.",
        "Permit me to demonstrate, sire.",
        "I shall show thee, my lord.",
        "Let me hold and release, sire.",
        "Shall I do the aiming, lord?",
        "Give me the fruit, my lord.",
        # Or send for someone. Anyone.
        "Shall I summon thy squire, sire?",
        "Perhaps a rest, my lord?",
        "Shall I fetch thee water, sire?",
        "Thy arm wearies, my lord. Rest.",
        "Sit awhile, sire. I shall wait.",
        "Shall we resume tomorrow, my lord?",
        "Let another try, sire. Anyone.",
        "Shall I call for aid, lord?",
        "Shall I fetch younger eyes, sire?",
        "Perhaps thy other hand, my lord?",
        "Shall I close mine eyes, sire?",
        "Would silence help, my lord?",
        "Shall I stop watching, sire?",
        "Command me, my lord. I obey.",
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
        # He takes the fruit and finishes the job.
        "I shall strike my own face.",
        "Let me finish this, my lord.",
        "I shall wound myself, sire. Gladly.",
        "Give me the fruit. I obey.",
        "I shall press it in, lord.",
        "Permit me, sire. It ends now.",
        "One blow, my lord. Mine own.",
        "I shall spare thee the labour.",
        "Rest, sire. I shall do it.",
        # The keeper of the record offers to destroy it.
        "This page shall be burnt, sire.",
        "I shall tear out the leaf.",
        "No ink for this, my lord.",
        "The chronicle forgets, sire. I promise.",
        "I shall write nothing, my lord.",
        "Let it be lost, sire.",
        "I shall blot it out, lord.",
        "The record ends here, my lord.",
        "Nothing shall be written, sire.",
        "I shall lose the page, lord.",
        "History need not know, sire.",
        "Thy grandchildren shall never learn, lord.",
        "The ledger is blind tonight, sire.",
        "I shall lie for thee, my lord.",
        "Let me forget, sire. I shall.",
        # And swears the household to silence.
        "The walls heard nothing, my lord.",
        "I saw nothing, sire. Nothing.",
        "No soul shall know, my lord.",
        "I shall swear I was struck.",
        "Thy secret is safe, sire.",
        "The household sleeps, my lord. Fortunate.",
        "I shall tell them thou hit.",
        "Let us speak no more, sire.",
        "This never happened, my lord.",
        "I shall deny it, sire. Always.",
        # Lying down inside the target area.
        "I shall lie upon the floor.",
        "Let me kneel before thee, sire.",
        "I shall crawl nearer, my lord.",
        "Place it upon me, sire.",
        "I shall not rise, my lord.",
        "Bind my feet, sire. I stray.",
        "Nail me still, my lord.",
        "I shall stand here forever, sire.",
        "Let me be thy wall, lord.",
        "I offer my whole body, sire.",
        # Grief, dismissal, and a request for penance.
        "I weep for thee, my lord.",
        "My tears are for thy trouble.",
        "Thy servant grieves, sire. Deeply.",
        "I have shamed thee, my lord.",
        "Forgive my existence, sire. I beg.",
        "Let me be dismissed, my lord.",
        "Send me away, sire. I fail.",
        "I am no use to thee.",
        "Replace me, my lord. Pray do.",
        "A better servant awaits thee, sire.",
        "I am the fault, my lord.",
        "My whole life hath failed thee.",
        "I was born poorly placed, sire.",
        "Even standing I fail thee, lord.",
        "I shall fast, my lord. Penance.",
        "Flog me, sire. It would help.",
        "Let me be struck by others.",
        "I shall hire a thrower, lord.",
        "Any hand, sire. Even mine own.",
        "Take my eyes, sire. I misled thee.",
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
    """Draws without repeating lately, so a pool feels as big as it is.

    Plain random.choice said the same thing twice in a row often enough to
    spoil it -- which is the one thing a taunt cannot do. The memory must stay
    smaller than the smallest pool drawn through it, or the fresh list empties
    every draw and this degrades silently back into random.choice.
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
