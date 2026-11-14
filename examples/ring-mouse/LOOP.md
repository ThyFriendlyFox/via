# The loop that made Signet

Signet was iterated in a Ralph loop: the same prompt, run again and again, each pass starting from
what the last one left on disk. A pass does one version. It reads the latest folder, judges it
against the checklist below, picks the findings that matter most, copies the folder to the next
version and answers them there, and stops when the new version's gates are GREEN and its pictures
are drawn. The loop ends when a pass finds nothing on the checklist worth a version.

The versions are the record: each README's "What changed" table lists the pass's findings and what
the version did about each, as [Last Hit](https://github.com/ThyFriendlyFox/vape-prototype) does.

## The prompt

```text
You are improving Signet, a mouse worn as a ring: 6 small boards round the finger, in
examples/ring-mouse/. Read the latest version folder (its README first). Then:

1. Run `workcenter gates <tile> --strict` for every tile and `make -C firmware test`.
2. Draw the pictures (`workcenter pictures <version>`) and look at every one.
3. Judge the version against LOOP.md's checklist. Write down each finding with its evidence:
   a gate's line, a picture, a measure, a datasheet's number.
4. Pick the findings that make the biggest difference to someone wearing it or looking at it.
5. `workcenter version new examples/ring-mouse <next>`, and answer them in the copy only.
6. Route, gate and draw the new version until every tile is GREEN and the pictures are whole.
7. Fill the new README's "What changed" table: each finding, the evidence, what changed.
8. Stop. Do not start the next pass in this one.
```

## The checklist

Function:

- Every tile `GREEN` under `--strict`, or each warning kept is named with its reason.
- Each feature reaches the radio: the strip's 3 channels, both clicks, the IMU's bus and interrupt,
  the gauge, the charger's state. Every joint's 8 pads name the same nets on both tiles.
- Every circuit question has a deck, and every bound holds at its corners.
- The firmware that turns sensor readings into mouse reports has host tests that can fail.

The ring:

- The tiles close: each joint's inner corners meet in the assembly's end view.
- Nothing but flat pads on an inner face: it rests on the finger.
- Every part stands on an outer face where a thumb or a knuckle will not catch it.
- The antenna points away from the finger and has no copper over it.

Looks:

- Each tile's parts line up on a grid, symmetric where the circuit allows.
- The legend reads, says what a reader needs, and nothing it does not.
- The finish is the stackup's: black mask, white legend, gold pads.
- The assembly shows the ring as a ring: the joints, the cell, the thumb's side.
