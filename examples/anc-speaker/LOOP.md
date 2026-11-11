# The loop that made Hush

Hush v0.1 was polished in a Ralph loop: the same prompt, run again and again, each iteration
starting from what the last one left on disk and from the log below. Unlike Signet's loop, which
made a version per pass, every iteration here came before v0.1's first push, so they all belong to
v0.1 (P22: a version takes what finishes the request it was made for). The log is the record; the
version README's Board section says what each review found and what changed.

## The prompt

```text
examples/anc-speaker/v0.1 is the workcenter's example of what people make with Via: a noise
cancelling speaker that hears the room with a mic and plays the inverse wave. It must be compact,
correct, and gorgeous: a board someone would want to hold and photograph. Read this file and its
log, do one iteration, and append to the log.

1. `workcenter design design.py --route --passes 20` (in the background, with a log), then
   `workcenter gates .`.
2. Render: `workcenter render . --strict --views schematic,2d,3d,layers`.
3. Fresh eyes: a reviewer who has not seen earlier rounds reads the images against the checklist
   and returns the 3 worst problems, each with where it is and why it matters.
4. Fix the worst problems that are real, checked in the files and not in the picture alone. Rules
   and gate failures first.
5. Append to the log: the iteration, the gates' verdict line, the reviewer's top 3, what changed,
   what is next.
```

## The checklist

Done when every line holds.

Gates
- `workcenter gates .` prints GREEN; DRC 0 errors, 0 unconnected, 0 parity; ERC 0/0.
- Warnings: only silkscreen clipped where a connector overhangs the edge, and the ones a model's
  own check deck prints, each named in the README.
- SIM: every deck's bounds hold at every corner; a bound judged at nominal says why.
- `workcenter render --strict` names no part without a 3D body.

Function
- The mic's port sits on the cone's axis; its decoupling within 2 mm of its VDD pin.
- The class-D amplifier and its speaker wires stay away from the mic's lines and the error
  amplifier.
- Every connector and control is reachable at the edge: USB-C, line in, the ANC switch, the trimmer.
- The speaker's polarity is marked.

Beauty
- Parts sit on concentric arcs, in blocks, with one orientation; no part looks dropped.
- Front silkscreen: few, deliberate labels, none touching a pad, a part or the edge.
- Back: the noise and its inverse resolve into one line; gold rims read cleanly and keep clear of
  holes and pads; no silk over a hole or a via; black mask, white silk, gold finish in the renders.
- The assembly with the CE40-4 under the ring reads at a glance: the cone shows through the windows.

Schematic
- Reads left to right in blocks; no wire wanders round the sheet; no text on a part or on other
  text.

## The log

**Iteration 0, setup.** Unrouted: ERC 0/0; DRC 83 unconnected, 0 parity, 4 silkscreen warnings at
the jack and the switch. The placement worked but read as scattered; a trial route showed F.Cu and
In2.Cu route the ring.

**Iteration 1.** Gates: GREEN with 6 warnings. The loop's numbers settled first: R14 6.2k and C16
1.2n held every bound at every corner, and the hum deck ran at every corner once its step control
was loosened (M142). The reviewer's top 3: the waves on the back ended in the jack's inner peg hole,
the jack's outer peg and the USB-C slots cut the outer gold rim, and about 25 vias stood under the
waves; the speaker's pads had no polarity mark, the switch no ON or OFF, the LED no label; the
schematic's text overlapped (fixed in the layout table before the review landed). Found in the
renders too: KiCad's named black mask rendered brown over the pour, and the mic's lid rendered
white. Changed: the waves start and end beside the jack's peg, and their band is a via keep-out; the
outer rim breaks at a hole within 0.3 mm of it; the holes moved in 0.5 mm; + and - at the speaker's
pads, ON beside the LED; a near-black mask at 95 % opacity; a steel lid. The switch's ends stay
unmarked: the PCM12's switching diagram was not to hand.

**Iteration 2.** The first route after those changes left U2's output pad walled in by the waves'
via band and 2 tracks: the waves moved in 0.2 mm and a hand via let it out. The rail deck searched
its peak from 20 kHz (M143). Gates: GREEN with 6 warnings. The GIFs' framing: whole at zoom 0.95;
1.0 and above clip the connectors that overhang the edge. The reviewer's top 3: the + and - turned
with the ring and read as "x" and "/"; the top band almost lined up; labels still touched parts on
the schematic. Nits: vias in the back's lettering, DEPTH touching the trimmer's outline, the music's
track across the lower spokes and the hub, the holes' pads 0.5 mm from the rim.

**Iteration 3.** Changed: the + and - upright; 22 passives on radial columns 8 degrees apart (the
chips stayed, as the hand copper depends on them); DEPTH inside the trimmer; a via keep-out under
each line of the back's lettering; track keep-outs on the 2 lower spokes; holes for button-head
screws with a 3.5 mm pad, 1 mm from the rim; the schematic's labels spaced. The router then
reached U2's output on F.Cu and the hand via hung on one layer, so it went. Gates: GREEN with 6
warnings; 426 segments, 12 vias, 6 ground stitches. Every checklist line holds but one: the mic's
value on the schematic crosses its OUT- wire, where KiCad's symbol puts it and the generator has no
field position to move it.
